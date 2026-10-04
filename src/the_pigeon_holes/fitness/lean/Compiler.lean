import Lean

/- Trusted compiler: inspect elaborated expressions, never interpret source text as maths. -/
open Lean Meta Elab Command

namespace FitnessCompiler

-- Parse without elaborating untrusted commands. This deliberately excludes tactic
-- blocks, metaprograms, attributes and custom syntax; it is not a general sandbox.
partial def inspectSyntax (s : Syntax) : Except String Unit := do
  match s with
  | .atom _ value =>
    if ["sorry", "admit", "axiom", "unsafe", "partial", "noncomputable", "by",
        "do", "@[", "set_option", "initialize", "where", "by_elab", "run_tac",
        "run_elab"].contains value then
      throw s!"unsupported source token: {value}"
  | .ident _ _ value _ =>
    if value == ``sorryAx then throw "sorryAx is forbidden"
  | .node _ _ children => for child in children do inspectSyntax child
  | .missing => throw "missing syntax"

elab "#check_fitness_source " file:str : command => do
  let source ← liftIO <| IO.FS.readFile file.getString
  let ctx := Parser.mkInputContext source file.getString
  let (header, state, messages) ← Parser.parseHeader ctx
  if messages.hasErrors then throwError "lean_compile_failed: malformed header"
  unless header[0].getArgs.isEmpty do throwError "unsupported_formalization: prelude"
  -- Imports may only come from the pinned mathematical/standard libraries.
  for imp in header[1].getArgs do
    let name := imp[2].getId.toString
    unless name.toList.all (fun c => c.isAlphanum || c == '_' || c == '.') do
      throwError "unsupported_formalization: unusual import name"
    unless name == "Mathlib" || name.startsWith "Mathlib." || name == "Std" ||
        name.startsWith "Std." || name == "Init" || name.startsWith "Init." do
      throwError "unsupported_formalization: import {name}"
  let pmctx : Parser.ParserModuleContext := { env := ← getEnv, options := ← getOptions }
  let mut state := state
  let mut messages := messages
  repeat
    let (stx, next, msgs) := Parser.parseCommand ctx pmctx state messages
    state := next
    messages := msgs
    if messages.hasErrors then throwError "lean_compile_failed: malformed Lean syntax"
    if stx.isOfKind ``Parser.Command.eoi then break
    unless [``Parser.Command.declaration, ``Parser.Command.namespace,
            ``Parser.Command.end, ``Parser.Command.open,
            ``Parser.Command.moduleDoc].contains stx.getKind do
      throwError "unsupported_formalization: command {stx.getKind}"
    match inspectSyntax stx with
    | .error e => throwError "unsupported_formalization: {e}"
    | .ok _ => pure ()


def jsonString (s : String) : Json := toJson s

partial def schema (e : Expr) : MetaM String := do
  let e ← whnf e
  if e.isConstOf ``Nat then return "Nat"
  if e.isConstOf ``Int then return "Int"
  if e.isAppOfArity ``List 1 then
    let a ← schema e.getAppArgs[0]!
    if a == "Nat" || a == "Int" then return "List " ++ a
  throwError "unsupported data type: {e}"

def render (e : Expr) : MetaM String := do
  withOptions (fun o => o.setBool `pp.fullNames true |>.setBool `pp.universes false) do
    return (← ppExpr e).pretty

-- Build a closed function from the instance binders and the chosen candidate.
def closed (xs : Array Expr) (c body : Expr) : MetaM String := do
  render (← mkLambdaFVars (xs.push c) body)

def compileBody (name : Name) (xs : Array Expr) (c body : Expr)
    (shape : String) : MetaM Json := do
  let body ← whnf body
  unless body.isAppOfArity ``And 2 do throwError "expected feasibility ∧ optimality"
  let feasible := body.getAppArgs[0]!
  let comparison ← whnf body.getAppArgs[1]!
  unless comparison.isForall do throwError "expected comparison with every alternative"
  forallBoundedTelescope comparison (some 1) fun ys rest => do
    let y := ys[0]!
    unless ← isDefEq (← inferType c) (← inferType y) do
      throwError "alternative has different candidate type"
    let rest ← whnf rest
    unless rest.isForall do throwError "expected feasibility implication"
    let .forallE _ premise result _ := rest | unreachable!
    if result.hasLooseBVars then throwError "dependent feasibility proof is unsupported"
    unless ← isDefEq premise (feasible.replaceFVar c y) do
      throwError "feasibility differs between candidate and alternative"
    -- Do not whnf Int.le: it unfolds into a pattern match on the operands.
    let offset := if result.isAppOfArity ``LE.le 4 then 2 else 0
    unless result.isAppOfArity ``LE.le 4 || result.isAppOfArity ``Nat.le 2 ||
        result.isAppOfArity ``Int.le 2 do
      throwError "objective comparison must be Nat.le or Int.le"
    let lhs := result.getAppArgs[offset]!
    let rhs := result.getAppArgs[offset + 1]!
    let objectiveType ← schema (← inferType lhs)
    unless objectiveType == "Nat" || objectiveType == "Int" do
      throwError "objective must be Nat or Int"
    let relation := mkConst (if objectiveType == "Nat" then ``Nat.le else ``Int.le)
    unless ← isDefEq result (mkApp2 relation lhs rhs) do
      throwError "nonstandard ordering instance"
    let max ← isDefEq lhs (rhs.replaceFVar c y)
    let min ← isDefEq rhs (lhs.replaceFVar c y)
    if max == min then throwError "ambiguous or different objective expressions"
    let objective := if max then rhs else lhs
    if objective.containsFVar y.fvarId! then throwError "objective contains alternative"
    let mut parameters := #[]
    for x in xs do
      parameters := parameters.push <| Json.mkObj [
        ("name", jsonString (← x.fvarId!.getUserName).toString),
        ("type", jsonString (← schema (← inferType x)))]
    return Json.mkObj [
      ("declaration", jsonString name.toString), ("shape", jsonString shape),
      ("parameters", Json.arr parameters),
      ("candidate_type", jsonString (← schema (← inferType c))),
      ("objective_type", jsonString objectiveType),
      ("direction", jsonString (if max then "maximize" else "minimize")),
      ("feasible", jsonString (← closed xs c feasible)),
      ("objective", jsonString (← closed xs c objective))]

def compileDeclaration (name : Name) : MetaM Json := do
  let info ← getConstInfo name
  unless info.levelParams.isEmpty do throwError "polymorphic declarations unsupported"
  let value ← match info with
    | .defnInfo d => pure d.value
    | .thmInfo t => pure t.type
    | _ => throwError "expected definition or theorem"
  let isTheorem := match info with | .thmInfo _ => true | _ => false
  let process := fun (xs : Array Expr) (body : Expr) => do
    let body ← whnf body
    if body.isAppOfArity ``Exists 2 then
      let ty := body.getAppArgs[0]!
      withLocalDeclD `candidate ty fun c => do
        compileBody name xs c (← whnf (mkApp body.getAppArgs[1]! c)) "exists"
    else
      if xs.isEmpty then throwError "no candidate binder"
      compileBody name xs.pop xs.back! body "predicate"
  let result ← if isTheorem then forallTelescope value process else lambdaTelescope value process
  let original ← if isTheorem then render info.type else pure name.toString
  return (result.setObjVal! "original" (jsonString original)).setObjVal! "kind"
    (jsonString (if isTheorem then "theorem" else "def"))

elab "#compile_fitness" : command => do
  let result ← liftTermElabM do
    let env ← getEnv
    let names := env.constants.toList.filterMap fun (n, _) =>
      if (env.getModuleIdxFor? n).isNone && !n.isInternal then some n else none
    let mut results := #[]
    let mut reasons := #[]
    for name in names do
      for ax in ← collectAxioms name do
        unless [``propext, ``Classical.choice, ``Quot.sound].contains ax do
          throwError "unsupported_formalization: forbidden axiom {ax} in {name}"
      try
        let item ← compileDeclaration name
        results := results.push item
      catch ex => reasons := reasons.push s!"{name}: {← ex.toMessageData.toString}"
    unless results.size == 1 do
      throwError "unsupported_formalization: expected exactly one optimization declaration, found {results.size}\n{String.intercalate "\n" reasons.toList}"
    let definitions := names.filter fun name =>
      match env.find? name with | some (.defnInfo _) => true | _ => false
    return results[0]!.setObjVal! "definitions" (toJson (definitions.map Name.toString))
  liftIO <| IO.println ("FITNESS_JSON:" ++ result.compress)

end FitnessCompiler
