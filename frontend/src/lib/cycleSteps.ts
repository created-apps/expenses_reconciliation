import type { CycleStatus } from '@/types'

export type StepName = 'statement' | 'invoices' | 'results' | 'export'

/** The step a reconciliation opens on, by how far it has got. */
export function stepForStatus(status: CycleStatus): StepName {
  switch (status) {
    case 'matched':
      return 'results'
    case 'exported':
      return 'export'
    case 'statement_confirmed':
    case 'invoices_extracted':
      return 'invoices'
    default:
      return 'statement'
  }
}

/**
 * Index of the furthest step that can be opened (steps after it are not clickable yet).
 * Invoices opens once the statement is confirmed; Results and Export come with matching.
 */
export function reachedIndex(status: CycleStatus): number {
  switch (status) {
    case 'matched':
    case 'exported':
      return 3
    case 'statement_confirmed':
    case 'invoices_extracted':
      return 1
    default:
      return 0
  }
}
