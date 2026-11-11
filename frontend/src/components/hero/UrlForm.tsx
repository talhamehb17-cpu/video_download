import { ArrowRight, ClipboardPaste, Link2, X } from 'lucide-react'
import { useId, useState, type FormEvent, type RefObject } from 'react'

import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'

interface UrlFormProps {
  value: string
  onChange: (value: string) => void
  onSubmit: (url: string) => void
  busy: boolean
  inputRef: RefObject<HTMLInputElement | null>
}

/** The link field. Validation here is only a courtesy; the server decides. */
export function UrlForm({ value, onChange, onSubmit, busy, inputRef }: UrlFormProps) {
  const fieldId = useId()
  const messageId = useId()
  const [message, setMessage] = useState<{ tone: 'error' | 'hint'; text: string } | null>(null)
  const focus = () => inputRef.current?.focus()

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const url = value.trim()
    if (!url) {
      setMessage({ tone: 'error', text: 'Paste a video link first.' })
      focus()
      return
    }
    if (/\s/.test(url)) {
      setMessage({ tone: 'error', text: "That doesn't look like a link. Remove the spaces and try again." })
      focus()
      return
    }
    setMessage(null)
    onSubmit(url)
  }

  const paste = async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim()
      if (!text) {
        setMessage({ tone: 'hint', text: 'Your clipboard is empty. Copy a video link first.' })
        focus()
        return
      }
      onChange(text)
      setMessage(null)
      focus()
    } catch {
      // Not every browser lets a page read the clipboard; pasting by keyboard always works.
      setMessage({ tone: 'hint', text: 'Your browser blocked clipboard access. Click the field and press Ctrl/⌘ + V.' })
      focus()
    }
  }

  return (
    <form onSubmit={submit} noValidate className="w-full">
      <label htmlFor={fieldId} className="sr-only">
        Video link
      </label>
      <div
        className={cn(
          'glow-border glass flex flex-col gap-2 rounded-[28px] p-2 transition-shadow duration-300 sm:flex-row sm:items-center sm:rounded-full',
          'focus-within:shadow-[0_0_0_4px_color-mix(in_oklab,var(--violet)_18%,transparent),var(--shadow-panel)]',
        )}
      >
        <div className="flex min-w-0 flex-1 items-center gap-3 pl-4 pr-1">
          <Link2 className="size-5 shrink-0 text-ink-mute" aria-hidden />
          <input
            id={fieldId}
            ref={inputRef}
            type="text"
            inputMode="url"
            name="url"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="go"
            placeholder="Paste a public video link…"
            value={value}
            onChange={(event) => {
              onChange(event.target.value)
              if (message?.tone === 'error') setMessage(null)
            }}
            aria-invalid={message?.tone === 'error' || undefined}
            aria-describedby={message ? messageId : undefined}
            className="h-12 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-mute sm:h-13 sm:text-base"
          />
          {value && !busy && (
            <button
              type="button"
              onClick={() => {
                onChange('')
                setMessage(null)
                focus()
              }}
              aria-label="Clear the link"
              className="grid size-8 shrink-0 place-items-center rounded-full text-ink-mute transition-colors hover:bg-glass-strong hover:text-ink"
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="glass"
            size="lg"
            onClick={paste}
            disabled={busy}
            icon={<ClipboardPaste className="size-4" aria-hidden />}
            className="flex-1 sm:flex-none"
          >
            Paste
          </Button>
          <Button type="submit" size="lg" loading={busy} className="flex-[1.6] sm:flex-none">
            {busy ? 'Analyzing' : 'Download'}
            {!busy && <ArrowRight className="size-4" aria-hidden />}
          </Button>
        </div>
      </div>
      <p
        id={messageId}
        role={message?.tone === 'error' ? 'alert' : undefined}
        className={cn(
          'mt-2.5 min-h-5 px-5 text-left text-[13px]',
          message?.tone === 'error' ? 'text-bad' : 'text-ink-mute',
        )}
      >
        {message?.text}
      </p>
    </form>
  )
}
