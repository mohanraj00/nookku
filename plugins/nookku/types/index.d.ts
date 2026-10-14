// The data of the pane, from `pane` of `nookku status --json` (#348). It holds no secret.
// `test` is the running test, else the latest test. `page` is `test`, `manual` or `none`.
// `lines` is the text of the pane, and `open` is true if the pane shows "Open chat".
export type PaneData = {
  test: string | null
  state: string | null
  turns: number | null
  page: string
  lines: string[]
  open: boolean
}

// `view` is the end of the output of `nookku view`, which the pane shows. `pane` is the state of
// the test. `opened` is the test for which the plugin opened the pane. `note` is the output of
// the last "Open chat", or the error output of `nookku status --json`.
export type NookkuState = {
  view: string
  pane?: PaneData | null
  opened?: string | null
  note?: string
}

declare module 'claude-code' {
  interface PluginState {
    'nookku': { state: NookkuState }
  }
}
