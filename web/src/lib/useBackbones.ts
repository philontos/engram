import { useState, useEffect } from 'react'
import { fetchBackbones, type BackboneSchema } from '@/api'

type BackbonesState = {
  backbones: BackboneSchema[]
  orphans: string[]
  ready: boolean
}

let _cache: BackbonesState | null = null
let _promise: Promise<BackbonesState> | null = null

const EMPTY: BackbonesState = { backbones: [], orphans: [], ready: false }

export function useBackbones(): BackbonesState {
  const [state, setState] = useState<BackbonesState>(() => _cache ?? EMPTY)
  useEffect(() => {
    if (_cache) return
    if (!_promise) {
      _promise = fetchBackbones().then(r => {
        const next: BackbonesState = {
          backbones: r.backbones || [],
          orphans:   r.orphan_domains || [],
          ready:     true,
        }
        _cache = next
        return next
      })
    }
    _promise.then(setState)
  }, [])
  return state
}

export function getBackbone(backbones: BackboneSchema[], key: string): BackboneSchema | undefined {
  return backbones.find(b => b.key === key)
}
