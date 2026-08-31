/** Reading an Adtributor segment label. */

export const UNMAPPED_NOTE =
  'rows that arrived before their master-data record and were bucketed rather than dropped';

/** Is this segment the UNKNOWN member of some dimension?
 *
 * Worth calling out rather than hiding. UNKNOWN is not a failed join we papered over:
 * conform buckets an unmatched member and raises a DQ flag, so the revenue is still
 * counted and still attributable. Shown bare it reads like a bug; labelled, it is the
 * system saying which rows it could not classify yet — usually a launch whose SKUs
 * reach the product master days after they start selling.
 */
export function isUnmapped(label: string): boolean {
  return label.split(' x ').some((part) => part.endsWith('=UNKNOWN'));
}
