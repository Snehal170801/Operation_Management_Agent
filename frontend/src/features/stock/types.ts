export interface OpenOrder {
  case_id: string
  case_number: string | null
  quantity: number | null
}

export interface StockItem {
  item_description: string
  quantity_available: number
  updated_at: string
  min_level: number | null
  target_level: number | null
  /** At or below the minimum level. */
  low: boolean
  /** How many to order to get back up to the target (only when low). */
  suggested_quantity: number | null
  /** A re-order for this item that is still in progress. */
  open_order: OpenOrder | null
  unit: string | null
  category: string | null
  /** The supplier always asked for a quote when a request includes this item. */
  preferred_vendor_id: string | null
  preferred_vendor_name: string | null
}

/** One change to a stock count: who, when, old and new value, why, and the case if there was one. */
export interface StockHistoryEntry {
  entry_id: string
  item_description: string
  old_quantity: number
  new_quantity: number
  /** new - old: positive when stock went up. */
  change: number
  reason: string
  reason_label: string
  actor: string
  /** false when an agent made the change. */
  by_a_person: boolean
  case_id: string | null
  case_number: string | null
  note: string | null
  created_at: string
}

/** Change an item's name, unit, category or preferred supplier (null clears). The count and levels have their own requests. */
export interface UpdateStockItemRequest {
  item_description: string
  new_description: string
  unit: string | null
  category: string | null
  preferred_vendor_id: string | null
}

export interface UpsertStockRequest {
  item_description: string
  quantity_available: number
}

export interface StockLevelsRequest {
  item_description: string
  min_level: number | null
  target_level: number | null
}

export interface ReorderRequest {
  item_description: string
  quantity: number
  needed_by?: string
  urgent: boolean
}

export interface ReorderResponse {
  case_id: string
  case_number: string | null
}
