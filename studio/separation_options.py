"""Validated separation settings, shared by CPU and GPU deployments."""
import os


def extraction_options(cuda_available):
    device = os.getenv('STUDIO_EXTRACTION_DEVICE', 'auto').strip().lower()
    if device == 'auto':
        device = 'cuda' if cuda_available else 'cpu'
    if device not in ('cpu', 'cuda'):
        raise ValueError('STUDIO_EXTRACTION_DEVICE must be auto, cpu or cuda.')
    if device == 'cuda' and not cuda_available:
        raise ValueError('CUDA was requested but is unavailable. Install a CUDA-enabled PyTorch build on a GPU host.')
    profile = os.getenv('STUDIO_EXTRACTION_PROFILE', 'fast' if device == 'cpu' else 'balanced').strip().lower()
    if profile not in ('balanced', 'fast'):
        raise ValueError('STUDIO_EXTRACTION_PROFILE must be balanced or fast.')
    threads = int(os.getenv('STUDIO_EXTRACTION_THREADS', str(min(4, os.cpu_count() or 1))))
    if not 1 <= threads <= 32:
        raise ValueError('STUDIO_EXTRACTION_THREADS must be between 1 and 32.')
    return {'device': device, 'profile': profile, 'threads': threads,
            'shifts': 0 if profile == 'fast' else 1,
            'overlap': .1 if profile == 'fast' else .25,
            'segment': 2.0 if profile == 'fast' else None}
