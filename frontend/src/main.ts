import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElDialog, ElDrawer, ElLoading, ElPagination, ElUpload } from 'element-plus'
import 'element-plus/dist/index.css'
import './styles.css'
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.use(ElLoading)
app.component(ElDialog.name!, ElDialog)
app.component(ElDrawer.name!, ElDrawer)
app.component(ElPagination.name!, ElPagination)
app.component(ElUpload.name!, ElUpload)
app.mount('#app')
