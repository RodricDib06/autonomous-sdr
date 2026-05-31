/* eslint-disable react-refresh/only-export-components */
import { type ReactNode } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

interface WrapperProps {
  children: ReactNode;
  initialRoute?: string;
}

function TestWrapper({ children, initialRoute = '/' }: WrapperProps) {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

type CustomRenderOptions = Omit<RenderOptions, 'wrapper'> & { initialRoute?: string };

export function renderWithProviders(ui: React.ReactElement, options?: CustomRenderOptions) {
  const { initialRoute, ...rest } = options ?? {};
  return render(ui, {
    wrapper: ({ children }) => <TestWrapper initialRoute={initialRoute}>{children}</TestWrapper>,
    ...rest,
  });
}
