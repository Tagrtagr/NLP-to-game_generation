import { Chat } from "./Chat";
import { GameFrame } from "./GameFrame";
import { useGenerate } from "./useGenerate";

export default function App() {
  const { state, start, cancel, savedGames, saveCurrent, loadSaved, saveError } = useGenerate();
  return (
    <div className="h-full flex bg-neutral-950 text-neutral-100">
      <Chat
        state={state}
        savedGames={savedGames}
        saveError={saveError}
        onSubmit={start}
        onCancel={cancel}
        onSave={saveCurrent}
        onLoadSaved={loadSaved}
      />
      <main className="flex-1 min-w-0">
        <GameFrame state={state} />
      </main>
    </div>
  );
}
