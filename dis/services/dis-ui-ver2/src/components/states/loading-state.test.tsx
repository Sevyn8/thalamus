import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LoadingState } from './LoadingState'

// FIX 2: LoadingState shows an animated indeterminate bar (pure CSS) ALONGSIDE the honest text
// label — the user sees active background work, not a static statement. The bar is aria-hidden;
// the announced signal stays the label on role=status.
describe('LoadingState', () => {
  it('renders the animated indeterminate bar and the text label', () => {
    const { container } = render(<LoadingState label="Analyzing your columns…" />)
    // the label is present + announced.
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Analyzing your columns…')
    // the animated bar element is present (decorative, aria-hidden) with its moving segment.
    const bar = container.querySelector('.loadingbar')
    expect(bar).not.toBeNull()
    expect(bar).toHaveAttribute('aria-hidden', 'true')
    expect(bar?.querySelector('i')).not.toBeNull()
  })

  it('defaults the label but still shows the bar', () => {
    const { container } = render(<LoadingState />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading...')
    expect(container.querySelector('.loadingbar i')).not.toBeNull()
  })
})
