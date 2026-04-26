import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { format } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import {
  ArrowLeft,
  Bell,
  BellOff,
  Trash2,
  Play,
  Loader2,
  Edit2,
  Check,
  X,
} from 'lucide-react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  Scatter,
  ScatterChart,
} from 'recharts'
import { toast } from 'sonner'
import {
  getWatch,
  getHistory,
  getSnapshots,
  getAlerts,
  updateWatch,
  deleteWatch,
  toggleActive,
  forceCheck,
} from '../api'

function InlineEdit({ value, onSave, type = 'text', placeholder = '' }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')

  function save() {
    onSave(draft === '' ? null : type === 'number' ? Number(draft) : draft)
    setEditing(false)
  }

  function cancel() {
    setDraft(value ?? '')
    setEditing(false)
  }

  if (!editing) {
    return (
      <span
        onClick={() => setEditing(true)}
        className="cursor-pointer group inline-flex items-center gap-1 hover:text-blue-600"
      >
        {value ?? <span className="text-gray-400 italic">{placeholder}</span>}
        <Edit2 className="w-3 h-3 opacity-0 group-hover:opacity-100 text-gray-400" />
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1">
      <input
        type={type}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="input py-0.5 px-2 text-sm w-40"
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') cancel()
        }}
      />
      <button onClick={save} className="p-1 text-green-600 hover:bg-green-50 rounded">
        <Check className="w-3 h-3" />
      </button>
      <button onClick={cancel} className="p-1 text-gray-400 hover:bg-gray-100 rounded">
        <X className="w-3 h-3" />
      </button>
    </span>
  )
}

function PriceChart({ history, maxPoints, alerts }) {
  const alertDates = new Set(
    (alerts || [])
      .filter((a) => a.success)
      .map((a) => a.sent_at?.slice(0, 10)),
  )

  const data = (history || []).map((d) => ({
    ...d,
    alert: alertDates.has(d.date) ? d.min_points : undefined,
  }))

  if (data.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center text-gray-400 text-sm">
        Sem dados de histórico
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11 }}
          tickFormatter={(v) => format(new Date(v + 'T12:00:00'), 'dd/MM')}
        />
        <YAxis
          tick={{ fontSize: 11 }}
          tickFormatter={(v) => `${Math.round(v / 1000)}k`}
          width={40}
        />
        <Tooltip
          formatter={(v, name) => [v.toLocaleString('pt-BR') + ' pts', name]}
          labelFormatter={(v) =>
            format(new Date(v + 'T12:00:00'), "dd 'de' MMM yyyy", { locale: ptBR })
          }
        />
        <Legend />
        <Line
          type="monotone"
          dataKey="min_points"
          name="Mín. pontos (LIGHT)"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
        />
        <Line
          type="monotone"
          dataKey="max_points"
          name="Máx. pontos"
          stroke="#e5e7eb"
          strokeWidth={1}
          dot={false}
          strokeDasharray="4 2"
        />
        {maxPoints && (
          <ReferenceLine
            y={maxPoints}
            stroke="#ef4444"
            strokeDasharray="4 2"
            label={{ value: 'Limite', position: 'right', fontSize: 10, fill: '#ef4444' }}
          />
        )}
        {data.some((d) => d.alert) && (
          <Line
            type="monotone"
            dataKey="alert"
            name="Alerta enviado"
            stroke="#f59e0b"
            strokeWidth={0}
            dot={{ r: 5, fill: '#f59e0b' }}
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  )
}

export default function WatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [watch, setWatch] = useState(null)
  const [history, setHistory] = useState([])
  const [snapshots, setSnapshots] = useState([])
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [historyDays, setHistoryDays] = useState(30)

  const loadData = useCallback(async () => {
    try {
      const [wRes, hRes, sRes, aRes] = await Promise.all([
        getWatch(id),
        getHistory(id, historyDays),
        getSnapshots(id, 1, 'LIGHT'),
        getAlerts(id),
      ])
      setWatch(wRes.data)
      setHistory(hRes.data)
      setSnapshots(sRes.data)
      setAlerts(aRes.data)
    } catch {
      toast.error('Erro ao carregar watch')
    } finally {
      setLoading(false)
    }
  }, [id, historyDays])

  useEffect(() => {
    loadData()
  }, [loadData])

  async function handlePatch(field, value) {
    try {
      const res = await updateWatch(id, { [field]: value })
      setWatch(res.data)
      toast.success('Atualizado')
    } catch {
      toast.error('Erro ao atualizar')
    }
  }

  async function handleToggle() {
    try {
      const res = await toggleActive(id)
      setWatch(res.data)
      toast.success(watch.active ? 'Pausado' : 'Ativado')
    } catch {
      toast.error('Erro ao alterar status')
    }
  }

  async function handleDelete() {
    if (!confirm('Excluir este monitor?')) return
    try {
      await deleteWatch(id)
      toast.success('Monitor excluído')
      navigate('/')
    } catch {
      toast.error('Erro ao excluir')
    }
  }

  async function handleCheck() {
    setChecking(true)
    try {
      const res = await forceCheck(id)
      toast.success(`Check concluído — ${res.data.new_snapshots} novos snapshots`)
      loadData()
    } catch {
      toast.error('Erro no check')
    } finally {
      setChecking(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
      </div>
    )
  }

  if (!watch) return null

  return (
    <div className="max-w-4xl">
      {/* Back */}
      <button
        onClick={() => navigate('/')}
        className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Dashboard
      </button>

      {/* Header */}
      <div className="card p-5 mb-5">
        <div className="flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold">
              {watch.origin} → {watch.destination}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              {format(new Date(watch.departure + 'T12:00:00'), "dd 'de' MMM yyyy", { locale: ptBR })}
              {watch.return_date &&
                ` → ${format(new Date(watch.return_date + 'T12:00:00'), "dd 'de' MMM yyyy", { locale: ptBR })}`}
            </p>
            <p className="text-sm text-gray-500 mt-2">
              Limite:{' '}
              <InlineEdit
                value={watch.max_points}
                type="number"
                placeholder="definir limite"
                onSave={(v) => handlePatch('max_points', v)}
              />{' '}
              pts
            </p>
            {(watch.notes !== undefined) && (
              <p className="text-sm text-gray-500 mt-1">
                Notas:{' '}
                <InlineEdit
                  value={watch.notes}
                  placeholder="adicionar notas"
                  onSave={(v) => handlePatch('notes', v)}
                />
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleToggle}
              className={watch.active ? 'btn-secondary' : 'btn-primary'}
            >
              {watch.active ? (
                <>
                  <BellOff className="w-4 h-4" /> Pausar
                </>
              ) : (
                <>
                  <Bell className="w-4 h-4" /> Ativar
                </>
              )}
            </button>
            <button onClick={handleCheck} disabled={checking} className="btn-secondary">
              {checking ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Forçar check
            </button>
            <button onClick={handleDelete} className="btn-danger">
              <Trash2 className="w-4 h-4" />
              Excluir
            </button>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="card p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Evolução de preço</h2>
          <div className="flex gap-1">
            {[7, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setHistoryDays(d)}
                className={`px-2 py-1 text-xs rounded ${
                  historyDays === d
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
        <PriceChart history={history} maxPoints={watch.max_points} alerts={alerts} />
      </div>

      {/* Snapshots */}
      <div className="card overflow-hidden mb-5">
        <div className="px-4 py-3 border-b border-gray-100">
          <h2 className="font-semibold">Snapshots recentes (LIGHT)</h2>
        </div>
        {snapshots.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">Sem snapshots ainda</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Data captura</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Pontos</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">R$ Taxa</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Voo</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Paradas</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {snapshots.map((s) => (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 text-gray-500 text-xs">
                    {format(new Date(s.captured_at), "dd/MM/yyyy HH:mm", { locale: ptBR })}
                  </td>
                  <td className="px-3 py-2 font-bold text-blue-700">
                    {s.points.toLocaleString('pt-BR')}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    R$ {s.taxes_brl.toFixed(2).replace('.', ',')}
                  </td>
                  <td className="px-3 py-2">{s.flight_number}</td>
                  <td className="px-3 py-2 text-gray-500">
                    {s.stops === 0 ? 'Direto' : `${s.stops} con.`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="font-semibold">Alertas enviados</h2>
          </div>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Data</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Canal</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {alerts.map((a) => (
                <tr key={a.id}>
                  <td className="px-3 py-2 text-gray-500 text-xs">
                    {format(new Date(a.sent_at), "dd/MM/yyyy HH:mm", { locale: ptBR })}
                  </td>
                  <td className="px-3 py-2">{a.channel}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`badge ${a.success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'}`}
                    >
                      {a.success ? 'Enviado' : 'Falhou'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
