import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './styles/index.css'
import './styles/glassmorphism.css'
import axios from 'axios'

const app = createApp(App)

app.use(createPinia())

// 添加axios请求拦截器
axios.interceptors.request.use(
  config => {
    const token = localStorage.getItem("token") || localStorage.getItem("access_token") || ""
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 添加axios响应拦截器：401时自动跳转登录页
axios.interceptors.response.use(
  response => response,
  error => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

app.use(router)
app.use(ElementPlus)

app.mount('#app')
