import { useNavigate } from 'react-router-dom'
import { format } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import { ArrowRight, Bell, BellOff, TrendingDown, TrendingUp } from 'lucide-react'
import { ResponsiveContainer, LineChart, Line, Tooltip } from 'recharts'
import { toast } from 'sonner'
import { toggleActive } from '../api'

function Sparkline({ data }) {
  if (!data || data.length === 0) return null
  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={data}>
        <Line
          type="monotone"
          dataKey="min_points"
          stroke="#3b82f6"
          strokeWidth={1.5}
          dot={false}
        />
        <Tooltip
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const d = payload[0].payload
            return (
              <div className="bg-white border border-gray-200 rounded px-2 py-1 text-xs shadow">
                <div className="font-medium">{d.date}</div>
                <div className="text-blue-600">{d.min_points?.toLocaleString('pt-BR')} pts</div>
              </div>
            )
          }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function WatchCard({ watch, history, onToggle }) {
  const navigate = useNavigate()
  const snap = watch.last_snapshot

  const prevPoint = history?.at(-2)?.min_points
  const lastPoint = history?.at(-1)?.min_points
  const delta = prevPoint && lastPoint ? lastPoint - prevPoint : null

  async function handleToggle(e) {
    e.stopPropagation()
    try {
      await toggleActive(watch.id)
      onToggle?.()
      toast.success(watch.active ? 'Watch pausado' : 'Watch ativado')
    } catch {
      toast.error('Erro ao alterar status')
    }
  }

  return (
    <div
      onClick={() => navigate(`/watch/${watch.id}`)}
      className={`card p-4 cursor-pointer hover:border-blue-300 transition-colors ${
        !watch.active ? 'opacity-60' : ''
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 font-semibold text-sm">
          <span>{watch.origin}</span>
          <ArrowRight className="w-3 h-3 text-gray-400" />
          <span>{watch.destination}</span>
        </div>
        <button
          onClick={handleToggle}
          title={watch.active ? 'Pausar' : 'Ativar'}
          className="p-1 rounded hover:bg-gray-100 transition-colors"
        >
          {watch.active ? (
            <Bell className="w-4 h-4 text-blue-600" />
          ) : (
            <BellOff className="w-4 h-4 text-gray-400" />
          )}
        </button>
      </div>

      {/* Dates */}
      <p className="text-xs text-gray-500 mb-3">
        {format(new Date(watch.departure), "dd 'de' MMM yyyy", { locale: ptBR })}
        {watch.return_date &&
          ` → ${format(new Date(watch.return_date), "dd 'de' MMM yyyy", { locale: ptBR })}`}
      </p>

      {/* Price */}
      {snap ? (
        <div className="flex items-end gap-2 mb-2">
          <span className="text-xl font-bold text-blue-700">
            {snap.points.toLocaleString('pt-BR')}
          </span>
          <span className="text-sm text-gray-500 mb-0.5">pts</span>
          <span className="text-sm text-gray-500 mb-0.5">
            + R$ {snap.taxes_brl.toFixed(2).replace('.', ',')}
          </span>
          {delta !== null && (
            <span
              className={`text-xs mb-0.5 flex items-center gap-0.5 ${
                delta < 0 ? 'text-green-600' : 'text-red-500'
              }`}
            >
              {delta < 0 ? (
                <TrendingDown className="w-3 h-3" />
              ) : (
                <TrendingUp className="w-3 h-3" />
              )}
              {Math.abs(delta).toLocaleString('pt-BR')}
            </span>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-400 mb-2">Nenhuma busca ainda</p>
      )}

      {/* Sparkline */}
      {history && history.length > 1 && (
        <div className="mt-1 -mx-1">
          <Sparkline data={history} />
        </div>
      )}

      {/* Max points badge */}
      {watch.max_points && (
        <div className="mt-2 text-xs text-gray-500">
          Limite:{' '}
          <span className="font-medium">{watch.max_points.toLocaleString('pt-BR')} pts</span>
        </div>
      )}
    </div>
  )
}
