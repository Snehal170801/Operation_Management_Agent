/** How a column should be drawn (decided by the server, so a new dataset needs no screen changes). */
export type ColumnKind =
  | 'text'
  | 'longtext'
  | 'note'
  | 'int'
  | 'money'
  | 'rating'
  | 'date'
  | 'datetime'
  | 'badge'
  | 'list'
  | 'case'

export interface StoreColumn {
  key: string
  label: string
  kind: ColumnKind
}

export interface DatasetSummary {
  key: string
  label: string
  description: string
  count: number
}

export interface DatasetGroup {
  label: string
  datasets: DatasetSummary[]
}

export interface StoreRoomOverview {
  groups: DatasetGroup[]
}

/** A case cell: link by `id`, show `number`. */
export interface CaseRef {
  id: string
  number: string | null
}

export type StoreRow = Record<string, string | number | string[] | CaseRef | null>

export interface DatasetPage {
  key: string
  label: string
  description: string
  columns: StoreColumn[]
  rows: StoreRow[]
  total: number
  limit: number
  offset: number
}
