export type NookkuTurn = { said: string; shown: string | null; ok: boolean }

// `test` is the folder of the latest test that this session started, or null.
export type NookkuState = { on: boolean | null; turns: NookkuTurn[]; test?: string | null }

declare module 'claude-code' {
  interface PluginState {
    'nookku': { state: NookkuState }
  }
}
