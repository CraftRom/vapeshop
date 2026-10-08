const paths = {
  catalog: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  search: <><circle cx="10.5" cy="10.5" r="7" /><path d="m16 16 5 5" /></>,
  cart: <><path d="M2 3h3l3 13h11l3-9H6" /><circle cx="9" cy="21" r="1" /><circle cx="18" cy="21" r="1" /></>,
  chat: <path d="M21 11a9 9 0 0 1-9 9H4l-3 2 2-6a9 9 0 1 1 18-5Z" />,
  profile: <><circle cx="12" cy="7" r="4" /><path d="M4 22v-3a8 8 0 0 1 16 0v3Z" /></>,
  heart: <path d="M20.5 4.5a5.5 5.5 0 0 0-8.5 1 5.5 5.5 0 0 0-8.5 7L12 21l8.5-8.5a5.5 5.5 0 0 0 0-8Z" />,
  sort: <><path d="M3 6h10M3 12h7M3 18h4M18 3v18m-3-3 3 3 3-3m-6-12 3-3 3 3" /></>,
  back: <path d="m15 4-8 8 8 8" />,
  share: <><path d="M12 15V2m-4 4 4-4 4 4M7 9H4v13h16V9h-3" /></>,
  box: <><path d="m12 3 9 5v10l-9 5-9-5V8Z M3 8l9 5 9-5M12 13v10M7.5 5.5l9 5" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  close: <path d="m5 5 14 14M19 5 5 19" />,
}

export function StoreIcon({ name, filled = false }) {
  return <svg className="store-icon" viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}
