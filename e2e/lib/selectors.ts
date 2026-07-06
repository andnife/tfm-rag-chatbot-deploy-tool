// Centralised i18n-aware (ES) selectors / labels. The smoke test hardcoded these
// inline; centralising makes maintenance and a future EN locale tractable.
// Verify/adjust against the live UI as each spec is written.
export const S = {
  login: {
    email: 'Email',
    password: 'Contraseña',
    submit: 'Entrar',
  },
  nav: {
    knowledgeHeading: 'Knowledge Bases',
    chatbotsHeading: 'Chatbots',
  },
  chatbots: {
    testLink: /Probar/, // each chatbot card's "test/playground" link
  },
  chat: {
    composerPlaceholder: 'Escribe tu mensaje...',
    // assistant bubbles render here; >3 chars means a real (non "...") answer
    assistantBubble: 'div.justify-start div.whitespace-pre-wrap',
    composerRow: 'div.flex.gap-2.items-end',
  },
  reindex: {
    confirmWord: 'REINDEX',
  },
} as const
