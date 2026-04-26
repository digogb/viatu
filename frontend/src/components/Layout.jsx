import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Plane, Search, LayoutDashboard, LogOut } from 'lucide-react'
import { toast } from 'sonner'
import { logout } from '../api'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/buscar', icon: Search, label: 'Buscar' },
]

export default function Layout() {
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
    toast.success('Sessão encerrada')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Sidebar */}
      <aside className="flex flex-col w-56 bg-white border-r border-gray-200 shrink-0">
        <div className="flex items-center gap-2 px-5 py-5 border-b border-gray-100">
          <Plane className="w-5 h-5 text-blue-600" />
          <span className="font-bold text-lg tracking-tight">Viatu</span>
        </div>

        <nav className="flex-1 p-3 space-y-1">
          {navItems.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                }`
              }
            >
              <Icon className="w-4 h-4" />
              {label}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-6 py-4 text-sm text-gray-500 hover:text-gray-700 border-t border-gray-100 transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Sair
        </button>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}
