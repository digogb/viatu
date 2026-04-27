import { useState, useEffect, useRef } from 'react'
import { format } from 'date-fns'
import { ptBR } from 'date-fns/locale'
import { Search, Star, Eye, Loader2, ChevronDown, ChevronUp, Calendar } from 'lucide-react'
import { toast } from 'sonner'
import { searchRange, searchCalendar, getJob, createWatchFromSearch } from '../api'

const ORIGINS = ['FOR', 'GRU', 'GIG', 'BSB', 'SSA', 'REC', 'CWB', 'POA', 'BEL', 'MAO']

function CalendarHeatmap({ days, onDayClick }) {
  if (!days || days.length === 0) return null

  const min = Math.min(...days.map((d) => d.points))
  const max = Math.max(...days.map((d) => d.points))
  const range = max - min || 1

  function colorClass(points) {
    const pct = (points - min) / range
    if (pct < 0.2) return 'bg-green-500 text-white'
    if (pct < 0.4) return 'bg-green-300'
    if (pct < 0.6) return 'bg-yellow-200'
    if (pct < 0.8) return 'bg-orange-300'
    return 'bg-red-400 text-white'
  }

  return (
    <div className="grid grid-cols-7 gap-1 mt-4">
      {['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'].map((d) => (
        <div key={d} className="text-center text-xs text-gray-400 font-medium py-1">{d}</div>
      ))}
      {days.map((day) => {
        const d = new Date(day.date + 'T12:00:00')
        return (
          <button
            key={day.date}
            onClick={() => onDayClick?.(day)}
            className={`rounded p-1 text-center text-xs font-medium hover:opacity-80 transition-opacity ${colorClass(day.points)}`}
            title={`${day.date}: ${day.points.toLocaleString('pt-BR')} pts`}
          >
            <div>{d.getDate()}</div>
            <div className="text-xs opacity-80">{Math.round(day.points / 1000)}k</div>
          </button>
        )
      })}
    </div>
  )
}

function MonitorModal({ prefill, onClose, onCreated }) {
  const [maxPoints, setMaxPoints] = useState(
    prefill?.points ? Math.floor(prefill.points * 0.9) : '',
  )
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleCreate() {
    setLoading(true)
    try {
      await createWatchFromSearch({
        origin: prefill.origin,
        destination: prefill.destination,
        departure: prefill.departure,
        return_date: prefill.return_date || null,
        max_points: maxPoints ? Number(maxPoints) : null,
        notes,
        cabin: 'Y',
        adults: 1,
      })
      toast.success('Monitor criado!')
      onCreated?.()
      onClose()
    } catch {
      toast.error('Erro ao criar monitor')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card p-6 w-full max-w-sm m-4">
        <h2 className="text-lg font-bold mb-4">Criar Monitor</h2>
        <p className="text-sm text-gray-600 mb-4">
          {prefill?.origin} → {prefill?.destination} em{' '}
          {prefill?.departure
            ? format(new Date(prefill.departure + 'T12:00:00'), "dd/MM/yyyy")
            : '—'}
        </p>
        <div className="space-y-3">
          <div>
            <label className="label">Máximo de pontos (alerta abaixo disto)</label>
            <input
              type="number"
              className="input"
              value={maxPoints}
              onChange={(e) => setMaxPoints(e.target.value)}
              placeholder="Ex: 30000"
            />
          </div>
          <div>
            <label className="label">Notas (opcional)</label>
            <input
              type="text"
              className="input"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Ex: férias de julho"
            />
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          <button onClick={onClose} className="btn-secondary flex-1 justify-center">
            Cancelar
          </button>
          <button onClick={handleCreate} disabled={loading} className="btn-primary flex-1 justify-center">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Criar Monitor'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ResultRow({ row, origin, destination }) {
  const [expanded, setExpanded] = useState(false)
  const [showMonitor, setShowMonitor] = useState(false)

  if (row.error) {
    return (
      <tr>
        <td className="px-3 py-2 text-sm">{row.date}</td>
        <td colSpan={4} className="px-3 py-2 text-sm text-red-500">{row.error}</td>
      </tr>
    )
  }

  const light = row.cheapest_light
  const options = row.options || []

  return (
    <>
      <tr className="hover:bg-gray-50">
        <td className="px-3 py-2 text-sm font-medium">
          {format(new Date(row.date + 'T12:00:00'), 'dd/MM', { locale: ptBR })}
        </td>
        <td className="px-3 py-2 text-sm font-bold text-blue-700">
          {light ? light.points.toLocaleString('pt-BR') : '—'}
        </td>
        <td className="px-3 py-2 text-sm text-gray-600">
          {light ? `R$ ${light.taxes_brl.toFixed(2).replace('.', ',')}` : '—'}
        </td>
        <td className="px-3 py-2 text-sm text-gray-500">{light?.flight_number || '—'}</td>
        <td className="px-3 py-2">
          <div className="flex gap-1">
            {options.length > 0 && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="p-1 rounded hover:bg-gray-200"
                title="Ver detalhes"
              >
                <Eye className="w-4 h-4 text-gray-500" />
              </button>
            )}
            <button
              onClick={() =>
                setShowMonitor(true)
              }
              className="p-1 rounded hover:bg-yellow-100"
              title="Monitorar"
            >
              <Star className="w-4 h-4 text-yellow-500" />
            </button>
          </div>
        </td>
      </tr>
      {expanded && options.length > 0 && (
        <tr>
          <td colSpan={5} className="px-3 pb-3">
            <div className="bg-gray-50 rounded-lg p-3 text-xs space-y-1">
              {options.map((opt, i) => (
                <div key={i} className="flex justify-between">
                  <span className="badge bg-blue-100 text-blue-700">{opt.fare_brand || 'N/A'}</span>
                  <span className="font-medium">{opt.points.toLocaleString('pt-BR')} pts</span>
                  <span className="text-gray-500">R$ {opt.taxes_brl.toFixed(2).replace('.', ',')}</span>
                  <span className="text-gray-500">{opt.flight_number}</span>
                  <span className="text-gray-400">{opt.stops === 0 ? 'Direto' : `${opt.stops} con.`}</span>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
      {showMonitor && (
        <MonitorModal
          prefill={{ origin, destination, departure: row.date, points: light?.points }}
          onClose={() => setShowMonitor(false)}
          onCreated={() => {}}
        />
      )}
    </>
  )
}

export default function SearchPage() {
  const [origin, setOrigin] = useState(localStorage.getItem('viatu_origin') || 'FOR')
  const [destination, setDestination] = useState('')
  const [searchType, setSearchType] = useState('range')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [calendarYear, setCalendarYear] = useState(new Date().getFullYear())
  const [calendarMonth, setCalendarMonth] = useState(new Date().getMonth() + 1)
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null)
  const [calendarDays, setCalendarDays] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [jobProgress, setJobProgress] = useState(0)
  const [jobDone, setJobDone] = useState(false)
  const pollRef = useRef(null)

  useEffect(() => {
    localStorage.setItem('viatu_origin', origin)
  }, [origin])

  useEffect(() => {
    return () => clearInterval(pollRef.current)
  }, [])

  function generateDates(from, to) {
    const dates = []
    const cur = new Date(from + 'T12:00:00')
    const end = new Date(to + 'T12:00:00')
    while (cur <= end) {
      dates.push(cur.toISOString().slice(0, 10))
      cur.setDate(cur.getDate() + 1)
    }
    return dates
  }

  async function handleSearch() {
    if (!destination || destination.length !== 3) {
      toast.error('Informe o destino (código IATA)')
      return
    }

    setLoading(true)
    setResults(null)
    setCalendarDays(null)
    setJobId(null)
    setJobDone(false)

    try {
      if (searchType === 'calendar') {
        const res = await searchCalendar({
          origin,
          destination: destination.toUpperCase(),
          year: calendarYear,
          month: calendarMonth,
        })
        setCalendarDays(res.data.days)
      } else {
        if (!dateFrom || !dateTo) {
          toast.error('Informe o período')
          setLoading(false)
          return
        }
        const dates = generateDates(dateFrom, dateTo)
        const res = await searchRange({
          origin,
          destination: destination.toUpperCase(),
          dates,
          cabin: 'Y',
          adults: 1,
        })

        if (res.data.job_id) {
          setJobId(res.data.job_id)
          setJobProgress(0)
          pollRef.current = setInterval(async () => {
            const jr = await getJob(res.data.job_id)
            setJobProgress(jr.data.progress)
            if (jr.data.status === 'done') {
              clearInterval(pollRef.current)
              setResults(jr.data.result?.results || [])
              setJobDone(true)
              setLoading(false)
            } else if (jr.data.status === 'error') {
              clearInterval(pollRef.current)
              toast.error(`Erro no job: ${jr.data.error}`)
              setLoading(false)
            }
          }, 2000)
          return
        }

        setResults(res.data.results || [])
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erro na busca')
    } finally {
      if (!jobId) setLoading(false)
    }
  }

  const sortedResults = results
    ? [...results].sort((a, b) => {
        const pa = a.cheapest_light?.points ?? Infinity
        const pb = b.cheapest_light?.points ?? Infinity
        return pa - pb
      })
    : null

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">Buscar voos</h1>

      {/* Form */}
      <div className="card p-5 mb-6">
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="label">Origem</label>
            <select
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              className="input"
            >
              {ORIGINS.map((o) => <option key={o}>{o}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Destino</label>
            <input
              type="text"
              value={destination}
              onChange={(e) => setDestination(e.target.value.toUpperCase())}
              placeholder="IGU, GRU..."
              maxLength={3}
              className="input uppercase"
            />
          </div>
        </div>

        {/* Search type */}
        <div className="mb-4">
          <label className="label">Tipo de busca</label>
          <div className="flex gap-3 flex-wrap">
            {[
              { value: 'range', label: 'Range de datas' },
              { value: 'calendar', label: 'Mês inteiro' },
            ].map(({ value, label }) => (
              <label key={value} className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="radio"
                  name="searchType"
                  value={value}
                  checked={searchType === value}
                  onChange={() => setSearchType(value)}
                  className="accent-blue-600"
                />
                {label}
              </label>
            ))}
          </div>
        </div>

        {/* Date inputs */}
        {searchType === 'range' && (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="label">De</label>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input" />
            </div>
            <div>
              <label className="label">Até</label>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="input" />
            </div>
          </div>
        )}

        {searchType === 'calendar' && (
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="label">Mês</label>
              <select value={calendarMonth} onChange={(e) => setCalendarMonth(Number(e.target.value))} className="input">
                {Array.from({ length: 12 }, (_, i) => (
                  <option key={i + 1} value={i + 1}>
                    {format(new Date(2024, i, 1), 'MMMM', { locale: ptBR })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Ano</label>
              <input
                type="number"
                value={calendarYear}
                onChange={(e) => setCalendarYear(Number(e.target.value))}
                className="input"
                min={2025}
                max={2030}
              />
            </div>
          </div>
        )}

        <button
          onClick={handleSearch}
          disabled={loading}
          className="btn-primary w-full justify-center"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          {loading ? 'Buscando...' : 'Buscar'}
        </button>
      </div>

      {/* Job progress */}
      {jobId && !jobDone && (
        <div className="card p-4 mb-4">
          <div className="flex items-center gap-3 mb-2">
            <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
            <span className="text-sm font-medium">Buscando em background... {jobProgress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-500"
              style={{ width: `${jobProgress}%` }}
            />
          </div>
        </div>
      )}

      {/* Calendar heatmap */}
      {calendarDays && (
        <div className="card p-5">
          <h2 className="font-semibold mb-1">
            {origin} → {destination.toUpperCase()} —{' '}
            {format(new Date(calendarYear, calendarMonth - 1, 1), 'MMMM yyyy', { locale: ptBR })}
          </h2>
          <p className="text-xs text-gray-500 mb-2">Clique em um dia para criar monitor</p>
          <CalendarHeatmap
            days={calendarDays}
            onDayClick={(day) => {
              // TODO: open monitor modal
            }}
          />
        </div>
      )}

      {/* Results table */}
      {sortedResults && sortedResults.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100">
            <span className="text-sm font-medium">{sortedResults.length} datas encontradas</span>
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Data</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Pontos LIGHT</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">R$ Taxa</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Voo</th>
                <th className="px-3 py-2 text-xs font-medium text-gray-500">Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sortedResults.map((row) => (
                <ResultRow
                  key={row.date}
                  row={row}
                  origin={origin}
                  destination={destination.toUpperCase()}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sortedResults && sortedResults.length === 0 && (
        <div className="card p-8 text-center text-gray-400">
          Nenhum resultado encontrado
        </div>
      )}
    </div>
  )
}
