import shutil


class DiskUsage:
    def percent(self, path):
        t, u, f = shutil.disk_usage(path)
        return (u / t) * 100 if t else 0.0
