import psutil
import time
import os

def format_bytes(bytes_value):
    """Format bytes to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} TB"

def monitor_memory(interval=2):
    """Monitor memory usage in real-time.
    
    Args:
        interval: Seconds between updates
    """
    process = psutil.Process(os.getpid())
    
    print("=" * 60)
    print("Memory Monitor - Press Ctrl+C to stop")
    print("=" * 60)
    
    peak_memory = 0
    try:
        while True:
            # Get memory info
            mem_info = process.memory_info()
            rss = mem_info.rss  # Resident Set Size (actual physical memory)
            vms = mem_info.vms  # Virtual Memory Size
            
            # Track peak
            if rss > peak_memory:
                peak_memory = rss
            
            # System memory
            sys_mem = psutil.virtual_memory()
            
            # Clear line and print stats
            print(f"\r"
                  f"RSS: {format_bytes(rss):>12} | "
                  f"VMS: {format_bytes(vms):>12} | "
                  f"Peak: {format_bytes(peak_memory):>12} | "
                  f"System: {sys_mem.percent:>5.1f}%",
                  end='', flush=True)
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print(f"Peak Memory Usage: {format_bytes(peak_memory)}")
        print(f"Final RSS: {format_bytes(rss)}")
        print("=" * 60)

if __name__ == "__main__":
    monitor_memory()
