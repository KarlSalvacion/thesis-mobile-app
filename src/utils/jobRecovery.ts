import AsyncStorage from '@react-native-async-storage/async-storage'

const ACTIVE_JOB_KEY = '@weedefy_active_job'

export type JobStage = 'upload' | 'processing' | 'compression'

export interface ActiveJob {
  job_id: string
  stage: JobStage
  timestamp: number
}

export async function saveActiveJob(job_id: string, stage: JobStage): Promise<void> {
  try {
    const jobData: ActiveJob = {
      job_id,
      stage,
      timestamp: Date.now()
    }
    await AsyncStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify(jobData))
    console.log(`💾 [JOB RECOVERY] Saved job ${job_id} at stage: ${stage}`)
  } catch (error) {
    console.error('❌ [JOB RECOVERY] Failed to save active job:', error)
  }
}

export async function getActiveJob(): Promise<ActiveJob | null> {
  try {
    const jobDataStr = await AsyncStorage.getItem(ACTIVE_JOB_KEY)
    if (!jobDataStr) return null
    
    const jobData: ActiveJob = JSON.parse(jobDataStr)
    console.log(`📋 [JOB RECOVERY] Retrieved job ${jobData.job_id} at stage: ${jobData.stage}`)
    return jobData
  } catch (error) {
    console.error('❌ [JOB RECOVERY] Failed to get active job:', error)
    return null
  }
}

export async function clearActiveJob(): Promise<void> {
  try {
    await AsyncStorage.removeItem(ACTIVE_JOB_KEY)
    console.log('🗑️ [JOB RECOVERY] Cleared active job')
  } catch (error) {
    console.error('❌ [JOB RECOVERY] Failed to clear active job:', error)
  }
}
