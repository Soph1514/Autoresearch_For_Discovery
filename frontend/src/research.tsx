import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import {
  applyEvent,
  type Snapshot,
  type ResearchClient,
  type ResearchEvent,
} from "./contracts";
interface State {
  snapshot: Snapshot | null;
  error: string | null;
  busy: boolean;
}
type Action =
  | { type: "snapshot"; snapshot: Snapshot }
  | { type: "event"; event: ResearchEvent }
  | { type: "error"; error: string | null }
  | { type: "busy"; busy: boolean };
function reducer(s: State, a: Action): State {
  switch (a.type) {
    case "snapshot":
      return { ...s, snapshot: a.snapshot };
    case "event":
      return {
        ...s,
        snapshot: s.snapshot ? applyEvent(s.snapshot, a.event) : null,
      };
    case "error":
      return { ...s, error: a.error };
    case "busy":
      return { ...s, busy: a.busy };
  }
}
const Context = createContext<ReturnType<typeof useResearchState> | null>(null);
function useResearchState(client: ResearchClient) {
  const [state, dispatch] = useReducer(reducer, {
    snapshot: null,
    error: null,
    busy: false,
  });
  const disconnect = useRef<() => void>(() => {});
  const epoch = useRef(0);
  useEffect(() => {
    const saved = sessionStorage.getItem("research-run");
    if (saved)
      void connect(saved).catch(() => {
        sessionStorage.removeItem("research-run");
      });
    return () => {
      epoch.current++;
      disconnect.current();
    };
  }, []);
  async function connect(id: string) {
    const token = ++epoch.current;
    disconnect.current();
    const snapshot = await client.getSnapshot(id);
    if (token !== epoch.current) return;
    dispatch({ type: "snapshot", snapshot });
    let sequence = snapshot.sequence;
    let recovering = false;
    const unsubscribe = client.subscribe(
      id,
      sequence,
      (event) => {
        if (
          token !== epoch.current ||
          recovering ||
          event.runId !== id ||
          event.sequence <= sequence
        )
          return;
        if (event.sequence !== sequence + 1) {
          recovering = true;
          queueMicrotask(() => {
            void connect(id).catch((e) =>
              dispatch({ type: "error", error: String(e) }),
            );
          });
          return;
        }
        sequence = event.sequence;
        dispatch({ type: "event", event });
      },
      (error) => {
        if (token === epoch.current) dispatch({ type: "error", error });
      },
    );
    disconnect.current = unsubscribe;
  }
  async function command(action: "start" | "pause" | "resume" | "stop") {
    dispatch({ type: "busy", busy: true });
    dispatch({ type: "error", error: null });
    try {
      if (action === "start") {
        const run = await client.startDemo();
        sessionStorage.setItem("research-run", run.id);
        await connect(run.id);
      } else if (state.snapshot) {
        const id = state.snapshot.run.id;
        if (action === "pause") await client.pauseRun(id);
        if (action === "resume") await client.resumeRun(id);
        if (action === "stop") await client.stopRun(id);
      }
    } catch (e) {
      dispatch({
        type: "error",
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      dispatch({ type: "busy", busy: false });
    }
  }
  return { ...state, command };
}
export function ResearchProvider({
  client,
  children,
}: {
  client: ResearchClient;
  children: ReactNode;
}) {
  const value = useResearchState(client);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useResearch() {
  const value = useContext(Context);
  if (!value) throw Error("Missing ResearchProvider");
  return value;
}
