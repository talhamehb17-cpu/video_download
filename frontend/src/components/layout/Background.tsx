/**
 * Ambient backdrop: three slow gradient orbs, a faint grid and a few drifting
 * points of light. Everything is CSS (transform/opacity only), so it runs on the
 * compositor and costs nothing on the main thread.
 */

const PARTICLES = [
  { left: '8%', top: '22%', size: 3, delay: '0s', duration: '7s' },
  { left: '17%', top: '64%', size: 2, delay: '2.4s', duration: '6s' },
  { left: '29%', top: '12%', size: 2, delay: '1.1s', duration: '8s' },
  { left: '41%', top: '78%', size: 3, delay: '3.6s', duration: '7s' },
  { left: '55%', top: '18%', size: 2, delay: '0.6s', duration: '6.5s' },
  { left: '66%', top: '58%', size: 2, delay: '4.2s', duration: '8s' },
  { left: '74%', top: '9%', size: 3, delay: '1.8s', duration: '7.5s' },
  { left: '83%', top: '72%', size: 2, delay: '2.9s', duration: '6s' },
  { left: '91%', top: '34%', size: 3, delay: '0.3s', duration: '9s' },
  { left: '48%', top: '44%', size: 2, delay: '5.1s', duration: '7s' },
] as const

export function Background() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      {/* base wash */}
      <div className="absolute inset-0 bg-[radial-gradient(120%_80%_at_50%_-10%,color-mix(in_oklab,var(--violet)_16%,transparent),transparent_60%)]" />

      {/* orbs */}
      <div
        className="absolute -left-[18%] -top-[22%] size-[62vmax] animate-orb-a rounded-full opacity-(--orb-opacity) blur-[90px] will-change-transform"
        style={{ background: 'radial-gradient(circle at 35% 35%, #7c5cff 0%, transparent 62%)' }}
      />
      <div
        className="absolute -right-[20%] top-[4%] size-[54vmax] animate-orb-b rounded-full opacity-(--orb-opacity) blur-[100px] will-change-transform"
        style={{ background: 'radial-gradient(circle at 60% 40%, #2f7bff 0%, transparent 60%)' }}
      />
      <div
        className="absolute bottom-[-30%] left-[22%] size-[50vmax] animate-orb-c rounded-full opacity-(--orb-opacity) blur-[110px] will-change-transform"
        style={{ background: 'radial-gradient(circle at 50% 50%, #12c2e0 0%, transparent 58%)' }}
      />

      {/* grid, fading out towards the edges */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(to right, var(--grid-line) 1px, transparent 1px), linear-gradient(to bottom, var(--grid-line) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
          maskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, #000 20%, transparent 78%)',
          WebkitMaskImage: 'radial-gradient(ellipse 75% 60% at 50% 30%, #000 20%, transparent 78%)',
        }}
      />

      {/* points of light */}
      {PARTICLES.map((particle) => (
        <span
          key={`${particle.left}-${particle.top}`}
          className="absolute animate-twinkle rounded-full bg-cyan shadow-[0_0_12px_2px_color-mix(in_oklab,var(--cyan)_60%,transparent)]"
          style={{
            left: particle.left,
            top: particle.top,
            width: particle.size,
            height: particle.size,
            animationDelay: particle.delay,
            animationDuration: particle.duration,
          }}
        />
      ))}

      {/* keeps long pages readable: the glow settles into the page colour */}
      <div className="absolute inset-x-0 bottom-0 h-[45%] bg-linear-to-t from-bg to-transparent" />
    </div>
  )
}
