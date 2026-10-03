"""BEq+ checker adapted from LeanInteract's official example."""

import json
from lean_interact import AutoLeanServer, Command
from lean_interact.interface import CommandResponse, LeanError, Pos, message_intersects_code
from lean_interact.utils import clean_last_theorem_string, indent_code, split_conclusion


def _check(server, code: str, line: int, proof: str, timeout: int) -> str | None:
    try:
        result = server.run(Command(cmd=code + indent_code("\nintros\nsymm_saturate\n" + proof, 2)), timeout=timeout)
        if isinstance(result, LeanError):
            return None
        start = Pos(line=line, column=0)
        if proof == "sorry":
            return proof if result.lean_code_is_valid(start_pos=start) else None
        if not result.lean_code_is_valid(start_pos=start, allow_sorry=False):
            return None
        if proof != "exact?":
            return proof
        for message in result.messages:
            if (message_intersects_code(message, start, None) and message.severity == "info"
                    and message.data.startswith("Try this:")):
                return message.data.split("Try this:", 1)[1].strip()
    except (TimeoutError, ConnectionAbortedError, json.JSONDecodeError):
        pass
    return None


def beq_plus(first: str, second: str, header: str, server: AutoLeanServer,
             timeout: int = 60) -> bool:
    """Return true only when BEq+ proves both implication directions."""
    base_name, target_name = "base_theorem", "reformulated_theorem"

    def prove_all(tactics):
        independent = " ; ".join(f"(all_goals try {t})" for t in tactics)
        combined = " ; ".join(f"(try {t})" for t in tactics)
        return f"all_goals intros\nfirst | ({independent}) | (all_goals ({combined}))"

    apply_all = prove_all(["tauto", "simp_all_arith!", "noncomm_ring", "exact?"])
    have_all = prove_all(["tauto", "simp_all_arith!", "exact? using this"])
    for base, target in ((first, second), (second, first)):
        try:
            base_code = header + "\n\n" + clean_last_theorem_string(base, base_name, add_sorry=True) + "\n\n"
            line = base_code.count("\n") + 1
            target_code = clean_last_theorem_string(target, target_name, add_sorry=False) + " := by"
        except ValueError:
            return False
        code = base_code + target_code
        if _check(server, code, line, "sorry", timeout) is None:
            return False
        exact = _check(server, code, line, "exact?", timeout)
        if exact and base_name in exact:
            continue
        # A target provable without the base is not evidence of implication.
        if _check(server, code, line, "assumption", timeout):
            return False
        if _check(server, code, line, f"apply {base_name}\n{apply_all}", timeout):
            continue
        independently_provable = False
        try:
            result = server.run(Command(cmd=target_code + have_all), timeout=timeout)
            independently_provable = (isinstance(result, CommandResponse)
                                      and result.lean_code_is_valid(allow_sorry=False))
        except (TimeoutError, ConnectionAbortedError, json.JSONDecodeError):
            pass
        if not independently_provable:
            start = split_conclusion(base_code)
            if start:
                conclusion = base_code[start:base_code.rfind(":=")].strip()
                have = (f"have {conclusion} := by\n"
                        + indent_code(f"apply_rules [{base_name}]\n{apply_all}", 2) + "\n")
                if _check(server, code, line, have + have_all, timeout):
                    continue
        for depth in range(5):
            proof = f"convert (config := .unfoldSameFun) {base_name} using {depth}\n{apply_all}"
            if _check(server, code, line, proof, timeout):
                break
        else:
            return False
    return True
