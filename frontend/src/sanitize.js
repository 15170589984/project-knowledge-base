import DOMPurify from 'dompurify'

const ALLOWED_TAGS = [
  'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'h1', 'h2', 'h3',
  'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a', 'hr', 'span',
]

export function sanitizeHtml(value) {
  if (!value) return ''
  return DOMPurify.sanitize(value, {
    ALLOWED_TAGS,
    ALLOWED_ATTR: ['href', 'target', 'rel'],
    ALLOW_DATA_ATTR: false,
  })
}
