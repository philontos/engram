import { useState, useEffect } from 'react'
import type { DimensionSchema } from '@/types'
import { fetchDimensions } from '@/api'

let _cache: DimensionSchema[] | null = null
let _promise: Promise<DimensionSchema[]> | null = null

export function useDimensionSchemas(): DimensionSchema[] {
  const [schemas, setSchemas] = useState<DimensionSchema[]>(() => _cache ?? [])
  useEffect(() => {
    if (_cache) return
    if (!_promise) _promise = fetchDimensions().then(d => { _cache = d; return d })
    _promise.then(setSchemas)
  }, [])
  return schemas
}

export function getDimSchema(schemas: DimensionSchema[], key: string): DimensionSchema | undefined {
  return schemas.find(s => s.key === key)
}
