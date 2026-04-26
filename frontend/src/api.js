import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// Auth
export const login = (password) => api.post('/auth/login', { password })
export const logout = () => api.post('/auth/logout')
export const getMe = () => api.get('/auth/me')

// Watches
export const listWatches = (activeOnly = true) =>
  api.get('/watches', { params: { active_only: activeOnly } })
export const getWatch = (id) => api.get(`/watches/${id}`)
export const createWatch = (data) => api.post('/watches', data)
export const createWatchFromSearch = (data) => api.post('/watches/from-search', data)
export const updateWatch = (id, data) => api.patch(`/watches/${id}`, data)
export const deleteWatch = (id) => api.delete(`/watches/${id}`)
export const toggleActive = (id) => api.put(`/watches/${id}/active`)
export const forceCheck = (id) => api.post(`/watches/${id}/check`)

// History & sub-resources
export const getHistory = (id, days = 30) =>
  api.get(`/watches/${id}/history`, { params: { days } })
export const getSnapshots = (id, page = 1, fareBrand) =>
  api.get(`/watches/${id}/snapshots`, { params: { page, fare_brand: fareBrand } })
export const getAlerts = (id) => api.get(`/watches/${id}/alerts`)

// Search
export const searchFlight = (data) => api.post('/search', data)
export const searchCalendar = (data) => api.post('/search/calendar', data)
export const searchRange = (data) => api.post('/search/range', data)

// Jobs
export const getJob = (id) => api.get(`/jobs/${id}`)
export const cancelJob = (id) => api.delete(`/jobs/${id}`)

export default api
