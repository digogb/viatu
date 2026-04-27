import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import WatchCard from '../components/WatchCard'
import { listWatches, getHistory } from '../api'

function SkeletonCard() {
  return (
    <div className="card p-4 animate-pulse">
      <div className="h-4 bg-gray-200 rounded w-24 mb-3" />
      <div className="h-3 bg-gray-200 rounded w-32 mb-4" />
      <div className="h-6 bg-gray-200 rounded w-36 mb-2" />
      <div className="h-10 bg-gray-100 rounded" />
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [watches, setWatches] = useState([])
  const [histories, setHistories] = useState({})
  const [loading, setLoading] = useState(true)
  const [showInactive, setShowInactive] = useState(false)
  const [allWatches, setAllWatches] = useState([])

  const loadData = useCallback(async () => {
    try {
      const [activeRes, allRes] = await Promise.all([
        listWatches(true),
        listWatches(false),
      ])
      setWatches(activeRes.data)
      setAllWatches(allRes.data)

      // Load histories in parallel
      const ids = activeRes.data.map((w) => w.id)
      const histEntries = await Promise.all(
        ids.map((id) =>
          getHistory(id, 30)
            .then((r) => [id, r.data])
            .catch(() => [id, []]),
        ),
      )
      setHistories(Object.fromEntries(histEntries))
    } catch {
      toast.error('Erro ao carregar watches')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const active = watches
  const inactive = allWatches.filter((w) => !w.active)

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {active.length} monitor{active.length !== 1 ? 'es' : ''} ativo{active.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadData} className="btn-secondary" title="Atualizar">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button onClick={() => navigate('/buscar')} className="btn-primary">
            <Plus className="w-4 h-4" />
            Nova busca
          </button>
        </div>
      </div>

      {/* Active watches grid */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : active.length === 0 ? (
        <div className="card p-12 text-center">
          <p className="text-gray-400 text-lg mb-4">Nenhum monitor ativo</p>
          <button onClick={() => navigate('/buscar')} className="btn-primary">
            <Plus className="w-4 h-4" />
            Criar primeiro monitor
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {active.map((w) => (
            <WatchCard
              key={w.id}
              watch={w}
              history={histories[w.id]}
              onToggle={loadData}
            />
          ))}
        </div>
      )}

      {/* Inactive section */}
      {inactive.length > 0 && (
        <div className="mt-8">
          <button
            onClick={() => setShowInactive((v) => !v)}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-4"
          >
            <ChevronDown
              className={`w-4 h-4 transition-transform ${showInactive ? 'rotate-180' : ''}`}
            />
            Pausados ({inactive.length})
          </button>

          {showInactive && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {inactive.map((w) => (
                <WatchCard key={w.id} watch={w} history={[]} onToggle={loadData} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
