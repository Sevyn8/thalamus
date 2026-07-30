import { useCallback, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

import { displayNameFor } from '../auth/displayName'
import { useAuth } from '../auth/useAuth'
import { useTenantSelf } from '../lib/dis-ui-server/tenant-self'
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

// The tenant identity chip: a display label plus a real copy control for the UUID.
//
// WHY COPY AND NOT JUST A TOOLTIP. The person who needs the tenant id is a TENANT ADMIN
// being asked "what's your tenant id?" by support — they have no gcloud and no console. A
// title tooltip is readable but cannot be pasted, so it is visible and useless. The title
// stays for hover; the button is what makes it usable.
//
// Degradation is deliberate rather than silent: without navigator.clipboard the UUID is
// REVEALED as selectable text and selected for the user, so a manual Ctrl-C still works.
function TenantChip({ label, tenantId }: { label: string; tenantId: string }) {
  const [copied, setCopied] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const uuidRef = useRef<HTMLSpanElement>(null)

  const copy = useCallback(() => {
    const writeText = navigator.clipboard?.writeText.bind(navigator.clipboard)
    if (writeText === undefined) {
      // No clipboard API (insecure context / old browser): reveal + select instead of
      // failing quietly, so the id is still obtainable.
      setRevealed(true)
      requestAnimationFrame(() => {
        const node = uuidRef.current
        if (node === null) return
        const range = document.createRange()
        range.selectNodeContents(node)
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
      })
      return
    }
    void writeText(tenantId)
      .then(() => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {
        setRevealed(true)
      })
  }, [tenantId])

  return (
    <>
      Tenant <b title={tenantId}>{label}</b>
      {revealed ? (
        <span className="tenantid" ref={uuidRef}>
          {tenantId}
        </span>
      ) : null}
      <button
        type="button"
        className="btn xs ghost"
        onClick={copy}
        // The accessible name carries the id itself, so a screen-reader user knows WHICH
        // id this copies without needing the visible label.
        aria-label={`Copy tenant ID ${tenantId}`}
        title={`Copy tenant ID ${tenantId}`}
      >
        {copied ? 'Copied' : 'Copy ID'}
      </button>
      {/* Announced to assistive tech as well as shown on the button. */}
      <span role="status" aria-live="polite" className="sr-only">
        {copied ? 'Tenant ID copied to clipboard' : ''}
      </span>
    </>
  )
}

export function Shell() {
  const { snapshot, profile, logout } = useAuth()
  const { pathname } = useLocation()
  const isPlatform = snapshot?.tenantId === null
  // TENANT-only: the hook disables itself when tenantId is null, so a PLATFORM session
  // fires no request (the endpoint would 403 it — a PLATFORM token has no own tenant).
  const tenantSelf = useTenantSelf(snapshot)
  const userLabel = profile === null ? null : displayNameFor(profile)
  const tenantId = snapshot?.tenantId ?? null
  // THE FALLBACK CHAIN: mirrored name -> display_code -> the raw UUID. Never blank, and
  // never a bare UUID when a name exists. display_code is the middle rung because CM's
  // wizard always generates one (tstco, nib-001) and it fits a chip where a long legal
  // name might not. A failed/absent mirror read falls straight through to the UUID: the
  // mirror is eventually consistent by design and the topbar must not be what breaks
  // when it lags.
  const tenantLabel = tenantSelf.data?.name ?? tenantSelf.data?.display_code ?? tenantId
  // Cross-app link back to the Customer Master launcher ("My Sevyn8"). Baked at
  // build time (dis-ui-ver2.Dockerfile ARG/ENV); a full-page nav to the CM
  // origin, so it is a plain <a>, not a react-router link. Rendered only when the
  // build arg is set, so dev builds without it show no dead affordance. Read at
  // render (not module scope) so it is stubbable in tests.
  const cmLauncherUrl = import.meta.env.VITE_CM_LAUNCHER_URL as string | undefined

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <img
            className="mark"
            src="/sevyn8-mark-motion.svg"
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
              {cmLauncherUrl ? (
                <a className="btn sm ghost" href={cmLauncherUrl}>
                  &larr; My Sevyn8
                </a>
              ) : null}
              <div className="scopepill">
                <span className="dot" />
                {isPlatform ? (
                  <>
                    Scope <b>All tenants</b>
                  </>
                ) : tenantId !== null ? (
                  <TenantChip label={tenantLabel ?? tenantId} tenantId={tenantId} />
                ) : (
                  <>
                    Tenant <b>unknown</b>
                  </>
                )}
              </div>
              {/* The signed-in person. Rendered only when the session actually carries a
                  display identity, so an absent profile shows nothing rather than a
                  placeholder. Expect an email-derived name: the Auth0 Action stamps no
                  name claim (see auth/displayName.ts). */}
              {userLabel === null ? null : (
                <div className="who" title={profile?.email ?? undefined}>
                  {userLabel}
                </div>
              )}
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
