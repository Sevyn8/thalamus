import { NavLink, Outlet, useLocation } from 'react-router'

import { useAuth } from '../auth/useAuth'
import { LockGlyph } from './PremiumLock'

// The persistent app shell (sidebar + topbar), styled to the DIS V2 mockups. Authenticated
// routes render inside it via <Outlet>. Nav is three groups; `locked` items carry a muted lock
// glyph (premium feature) but stay clickable — the route is unchanged. The `●` glyph is the
// mockups' own icon placeholder (they ship no SVG icons); a real icon set is a separate decision.

type NavItem = { label: string; to: string; locked?: boolean }
type NavGroup = { label: string; items: NavItem[] }

const NAV: NavGroup[] = [
  {
    label: 'Operate',
    items: [
      { label: 'Dashboard', to: '/' },
      { label: 'Configured Data Sources', to: '/pipelines' },
      { label: 'Ingestion Runs', to: '/ingestion-runs' },
      { label: 'Data Quality & History', to: '/data-quality' },
    ],
  },
  {
    label: 'Sources & Data',
    items: [
      { label: 'Connect a Data Source', to: '/connect' },
      { label: 'Data Ingestion Templates', to: '/templates' },
      { label: 'Connector Health', to: '/connector-health' },
      { label: 'Schema Drift & Changes', to: '/schema-drift', locked: true },
      { label: 'Canonical Explorer', to: '/canonical' },
    ],
  },
  {
    label: 'Govern',
    items: [
      { label: 'Credentials & Secrets', to: '/credentials', locked: true },
      { label: 'Audit & Version History', to: '/audit' },
      { label: 'Needs Attention', to: '/notifications' },
    ],
  },
]

function crumbFor(pathname: string): string {
  if (pathname.startsWith('/templates')) return 'Data Ingestion Templates'
  const match = NAV.flatMap((g) => g.items).find(
    (i) => i.to !== '/' && pathname.startsWith(i.to),
  )
  return match?.label ?? 'Dashboard'
}

export function Shell() {
  const { snapshot, logout } = useAuth()
  const { pathname } = useLocation()
  const isPlatform = snapshot?.tenantId === null

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <img
            className="mark"
            src="/sevyn8-mark-animated.svg"
            alt="Sevyn8"
            width={26}
            height={26}
          />
          <div className="wordmark">Sevyn8</div>
          <div className="tag">DIS</div>
        </div>
        {NAV.map((group) => (
          <div className="navgrp" key={group.label}>
            <div className="lbl">{group.label}</div>
            <div className="nav">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => (isActive ? 'on' : '')}
                >
                  <span className="ico" aria-hidden="true">
                    &#9679;
                  </span>
                  {item.label}
                  {item.locked ? (
                    <span className="lock" title="Premium feature">
                      <LockGlyph size={12} />
                    </span>
                  ) : null}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
        <div className="foot">Data Ingestion System</div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="spectrum" />
          <div className="bar">
            <div className="crumb">
              <b>{crumbFor(pathname)}</b>
            </div>
            <div className="scope">
              <div className="scopepill">
                <span className="dot" />
                {isPlatform ? (
                  <>
                    Scope <b>All tenants</b>
                  </>
                ) : (
                  <>
                    Tenant <b>{snapshot?.tenantId ?? 'unknown'}</b>
                  </>
                )}
              </div>
              <div className="avatar" aria-hidden="true">
                {isPlatform ? 'OP' : 'TN'}
              </div>
              <button type="button" className="btn sm ghost" onClick={logout}>
                Log out
              </button>
            </div>
          </div>
        </div>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
