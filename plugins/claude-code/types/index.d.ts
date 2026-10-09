export type NookuTurn = { said: string; shown: string | null; ok: boolean }

// `test` is the folder of the latest test that this session started, or null.
export type NookuState = { on: boolean | null; turns: NookuTurn[]; test?: string | null }

declare module 'claude-code' {
  interface PluginState {
    'nooku': { state: NookuState }
  }
}
