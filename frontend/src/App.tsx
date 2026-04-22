export default function App() {
  return (
    <div className="h-full flex">
      <aside className="w-2/5 border-r border-neutral-800 p-4 flex flex-col">
        <h1 className="text-lg font-semibold">Godot Agent</h1>
        <p className="text-sm text-neutral-400 mt-1">
          Describe a game. Watch it build. Play it.
        </p>
        <div className="flex-1 mt-4 overflow-auto text-sm text-neutral-500">
          (chat coming online in step 11)
        </div>
      </aside>
      <main className="flex-1 grid place-items-center text-neutral-500">
        <div>Game iframe mounts here.</div>
      </main>
    </div>
  );
}
