import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Users2, Flame } from 'lucide-react';
import { StatCard } from '../../../components/StatCard';

describe('StatCard', () => {
  it('renders title and numeric value', () => {
    render(<StatCard title="Total Leads" value={42} icon={Users2} />);
    expect(screen.getByText('Total Leads')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders string value', () => {
    render(<StatCard title="Open Rate" value="41%" icon={Users2} />);
    expect(screen.getByText('41%')).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    render(<StatCard title="Total Leads" value={42} icon={Users2} sub="all time" />);
    expect(screen.getByText('all time')).toBeInTheDocument();
  });

  it('does not render subtitle when omitted', () => {
    render(<StatCard title="Total Leads" value={42} icon={Users2} />);
    expect(screen.queryByText('all time')).not.toBeInTheDocument();
  });

  it('shows skeleton and hides value when loading', () => {
    const { container } = render(<StatCard title="Total Leads" value={42} icon={Users2} loading />);
    expect(container.querySelector('.skeleton')).toBeInTheDocument();
    expect(screen.queryByText('42')).not.toBeInTheDocument();
  });

  it('renders positive trend with up arrow', () => {
    render(<StatCard title="Leads" value={10} icon={Flame} trend={{ value: 15, label: 'vs last week' }} />);
    expect(screen.getByText(/15/)).toBeInTheDocument();
    expect(screen.getByText('vs last week')).toBeInTheDocument();
    expect(screen.getByText(/▲/)).toBeInTheDocument();
  });

  it('renders negative trend with down arrow', () => {
    render(<StatCard title="Leads" value={10} icon={Flame} trend={{ value: -8, label: 'vs last week' }} />);
    expect(screen.getByText(/▼/)).toBeInTheDocument();
    expect(screen.getByText(/8/)).toBeInTheDocument();
  });

  it('renders em-dash as value', () => {
    render(<StatCard title="Leads" value="—" icon={Users2} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('accepts all accent colors without error', () => {
    const accents = ['violet', 'emerald', 'orange', 'red', 'blue'] as const;
    for (const accent of accents) {
      const { unmount } = render(<StatCard title="T" value={1} icon={Users2} accent={accent} />);
      unmount();
    }
  });
});
