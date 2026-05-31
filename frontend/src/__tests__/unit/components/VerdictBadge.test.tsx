import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VerdictBadge } from '../../../components/VerdictBadge';

describe('VerdictBadge', () => {
  it('renders Hot label', () => {
    render(<VerdictBadge verdict="Hot" />);
    expect(screen.getByText('Hot')).toBeInTheDocument();
  });

  it('renders Warm label', () => {
    render(<VerdictBadge verdict="Warm" />);
    expect(screen.getByText('Warm')).toBeInTheDocument();
  });

  it('renders Cold label', () => {
    render(<VerdictBadge verdict="Cold" />);
    expect(screen.getByText('Cold')).toBeInTheDocument();
  });

  it('renders em-dash for null verdict', () => {
    const { container } = render(<VerdictBadge verdict={null} />);
    expect(container.textContent).toContain('—');
  });

  it('renders em-dash for undefined verdict', () => {
    const { container } = render(<VerdictBadge verdict={undefined} />);
    expect(container.textContent).toContain('—');
  });

  it('renders secondary badge for unknown verdict string', () => {
    render(<VerdictBadge verdict="Pending" />);
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });
});
