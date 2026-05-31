import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Users2 } from 'lucide-react';
import { NoData } from '../../../components/common/NoData';

describe('NoData', () => {
  it('renders default message', () => {
    render(<NoData />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
  });

  it('renders custom message', () => {
    render(<NoData message="No leads found" />);
    expect(screen.getByText('No leads found')).toBeInTheDocument();
  });

  it('renders an icon', () => {
    const { container } = render(<NoData />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });

  it('renders a custom icon', () => {
    const { container } = render(<NoData icon={Users2} />);
    expect(container.querySelector('svg')).toBeInTheDocument();
  });
});
