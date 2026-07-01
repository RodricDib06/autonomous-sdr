import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Separator } from '../../../components/ui/separator';

describe('Separator', () => {
  it('renders a horizontal separator by default', () => {
    const { container } = render(<Separator />);
    const el = container.firstChild as HTMLElement;
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('h-[1px]');
    expect(el.className).toContain('w-full');
  });

  it('renders a vertical separator when orientation is vertical', () => {
    const { container } = render(<Separator orientation="vertical" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain('h-full');
    expect(el.className).toContain('w-[1px]');
  });

  it('merges custom className', () => {
    const { container } = render(<Separator className="my-4" />);
    const el = container.firstChild as HTMLElement;
    expect(el.className).toContain('my-4');
  });
});
