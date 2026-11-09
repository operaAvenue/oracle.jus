import request from './index'

export function loginWithGoogle(data) {
  return request({
    url: '/api/auth/google',
    method: 'post',
    data
  })
}

export function getMe() {
  return request({
    url: '/api/auth/me',
    method: 'get'
  })
}

export function logoutUser() {
  return request({
    url: '/api/auth/logout',
    method: 'post'
  })
}

export function getPublicConfig() {
  return request({
    url: '/api/auth/config',
    method: 'get'
  })
}

// Admin APIs
export function getAdminUsers() {
  return request({
    url: '/api/admin/users',
    method: 'get'
  })
}

export function updateAdminUser(userId, data) {
  return request({
    url: `/api/admin/users/${userId}`,
    method: 'put',
    data
  })
}

export function deleteAdminUser(userId) {
  return request({
    url: `/api/admin/users/${userId}`,
    method: 'delete'
  })
}

export function getAdminSettings() {
  return request({
    url: '/api/admin/settings',
    method: 'get'
  })
}

export function updateAdminSettings(data) {
  return request({
    url: '/api/admin/settings',
    method: 'post',
    data
  })
}

export function uploadAdminAsset(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: '/api/admin/upload',
    method: 'post',
    data: formData,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

// Admin LLM APIs
export function getAdminLLMSettings() {
  return request({
    url: '/api/admin/llm',
    method: 'get'
  })
}

export function detectAdminLLMProvider(apiKey) {
  return request({
    url: '/api/admin/llm/detect',
    method: 'post',
    data: { api_key: apiKey }
  })
}

export function testAdminLLMConnection(data) {
  return request({
    url: '/api/admin/llm/test',
    method: 'post',
    data
  })
}

export function saveAdminLLMSettings(data) {
  return request({
    url: '/api/admin/llm/save',
    method: 'post',
    data
  })
}

// Payments API
export function createMercadoPagoPreference() {
  return request({
    url: '/api/payments/mercadopago/preference',
    method: 'post'
  })
}

export function getPaymentStatus() {
  return request({
    url: '/api/payments/status',
    method: 'get'
  })
}
