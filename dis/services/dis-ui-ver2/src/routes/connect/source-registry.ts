// The source catalog for the Connect page. Operator design: each SOURCE is its own card
// carrying its own journey (the generic transport-method tiles are retired). Cards render
// from this registry; adding a source is one entry here plus its journey component/route.
//
// Transport methods (API pull / webhook / SFTP / iPaaS) are deliberately NOT here: they are
// how data arrives, not sources. A future SFTP-delivered source arrives as its own card.

export type SourceStatus = 'active' | 'coming_soon'

export type SourceCard = {
  // Stable registry key (not a config.sources source_id; that is minted inside the journey).
  id: string
  name: string
  // A unicode mark (v2 ships no icon lib), matching the existing choice-tile glyph style.
  glyph: string
  description: string
  status: SourceStatus
  // The journey route. Present iff status === 'active'; coming-soon cards are non-navigable.
  route?: string
}

export const SOURCE_CARDS: SourceCard[] = [
  {
    id: 'manual_csv',
    name: 'Manual CSV',
    glyph: '▦',
    description: 'Upload files on demand.',
    status: 'active',
    route: '/connect/csv',
  },
  {
    id: 'square',
    name: 'Square',
    glyph: '□',
    description: 'Pull sales and catalogue across your Square locations.',
    status: 'active',
    route: '/connect/square',
  },
  {
    id: 'clover',
    name: 'Clover',
    glyph: '♣',
    description: 'Live transaction data from your Clover merchant account.',
    status: 'coming_soon',
  },
  {
    id: 'shopify',
    name: 'Shopify',
    glyph: 'S',
    description: 'Orders, products, and inventory from your Shopify store.',
    status: 'coming_soon',
  },
]
