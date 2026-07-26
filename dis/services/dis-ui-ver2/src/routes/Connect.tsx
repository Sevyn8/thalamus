import { useNavigate } from 'react-router'

import { SOURCE_CARDS } from './connect/source-registry'

// Connect a data source: a catalog-driven source-card grid (operator design). Each source is
// its own card carrying its own journey. Active cards navigate to their journey route; coming-
// soon cards are badged and non-navigable. Manual CSV -> the existing CSV wizard (untouched,
// at /connect/csv); Square -> the OAuth journey (/connect/square).

export function Connect() {
  const navigate = useNavigate()
  return (
    <>
      <div className="pagehead">
        <div>
          <h1>Connect a Data Source</h1>
        </div>
      </div>
      <div className="choicegrid">
        {SOURCE_CARDS.map((card) => {
          const comingSoon = card.status === 'coming_soon'
          return (
            <button
              key={card.id}
              type="button"
              className="choice"
              disabled={comingSoon}
              aria-disabled={comingSoon}
              onClick={() => {
                if (!comingSoon && card.route !== undefined) navigate(card.route)
              }}
            >
              {comingSoon ? <span className="badge b-mut choice__soon">Coming soon</span> : null}
              <div className="ic">{card.glyph}</div>
              <div className="t">{card.name}</div>
              <div className="d">{card.description}</div>
            </button>
          )
        })}
      </div>
    </>
  )
}
