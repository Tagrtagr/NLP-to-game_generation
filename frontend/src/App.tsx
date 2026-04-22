import { Chat } from "./Chat";
import { GameFrame } from "./GameFrame";
import { useGenerate } from "./useGenerate";

export default function App() {
  const { state, start, cancel } = useGenerate();
  return (
    <div className="h-full flex bg-neutral-950 text-neutral-100">
      <Chat state={state} onSubmit={start} onCancel={cancel} />
      <main className="flex-1 min-w-0">
        <GameFrame state={state} />
      </main>
    </div>
  );
}
