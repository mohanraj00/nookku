export type VerbatimRelayTurn = { said: string; shown: string | null; ok: boolean }

// `test` is the folder of the latest test that this session started, or null.
export type VerbatimRelayState = { on: boolean | null; turns: VerbatimRelayTurn[]; test?: string | null }

declare module 'claude-code' {
  interface PluginState {
    'verbatim-relay': { state: VerbatimRelayState }
  }
}
