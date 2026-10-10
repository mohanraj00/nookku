// `view` is the end of the output of `nookku view`, which the pane shows.
export type NookkuState = { view: string }

declare module 'claude-code' {
  interface PluginState {
    'nookku': { state: NookkuState }
  }
}
