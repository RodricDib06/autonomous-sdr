import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Loading } from '../../../components/common/Loading';

describe('Loading', () => {
  it('renders default loading text', () => {
    render(<Loading />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders custom text', () => {
    render(<Loading text="Fetching leads…" />);
    expect(screen.getByText('Fetching leads…')).toBeInTheDocument();
  });

  it('renders a spinning element', () => {
    const { container } = render(<Loading />);
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('has a status role for accessibility', () => {
    render(<Loading />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
