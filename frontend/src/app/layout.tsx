import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'MediBot - MediAssist Assistant',
  description: 'Intelligent assistant for MediAssist Health Network',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var theme = localStorage.getItem('medibot-theme');
                  if (theme === 'dark' || (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                    document.documentElement.setAttribute('data-theme', 'dark');
                  } else {
                    document.documentElement.setAttribute('data-theme', 'light');
                  }
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body style={{ margin: 0, fontFamily: 'system-ui, -apple-system, sans-serif' }}>{children}</body>
    </html>
  )
}
