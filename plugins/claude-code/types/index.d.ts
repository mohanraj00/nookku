export type VerbatimRelayTurn = { said: string; shown: string | null; ok: boolean }

export type VerbatimRelayState = { on: boolean | null; turns: VerbatimRelayTurn[] }

declare module 'claude-code' {
  interface PluginState {
    'verbatim-relay': { state: VerbatimRelayState }
  }
}
