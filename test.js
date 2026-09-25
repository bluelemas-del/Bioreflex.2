import { supabase } from './supabaseClient.js'

async function testInsert() {
  const { data, error } = await supabase
    .from('bioreflex_data')
    .insert([{ sample_name: 'Sample 1', metric_value: 98.6, notes: 'First test entry' }])

  if (error) console.error('Insert error:', error)
  else console.log('Successfully inserted!', data)
}

testInsert()