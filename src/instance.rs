//! One running desktop instance per user, independent of executable path or port.
use std::{
    fs::{self, File, OpenOptions, TryLockError},
    io,
    path::Path,
};

pub struct InstanceGuard {
    _file: File,
}
impl InstanceGuard {
    pub fn acquire() -> io::Result<Option<Self>> {
        let dirs = directories::BaseDirs::new()
            .ok_or_else(|| io::Error::other("無法找到使用者資料目錄"))?;
        Self::acquire_at(&dirs.data_local_dir().join("phone-pad/writethere.lock"))
    }

    fn acquire_at(path: &Path) -> io::Result<Option<Self>> {
        let parent = path
            .parent()
            .ok_or_else(|| io::Error::other("單一執行鎖路徑無效"))?;
        fs::create_dir_all(parent)?;
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path)?;
        match file.try_lock() {
            Ok(()) => Ok(Some(Self { _file: file })),
            Err(TryLockError::WouldBlock) => Ok(None),
            Err(TryLockError::Error(error)) => Err(error),
        }
    }
}
// Closing the handle releases the OS lock, including after process termination.
// Never delete the file on Drop: unlinking would allow two different lock inodes.

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn duplicate_is_blocked_and_leftover_file_does_not_block_restart() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("instance.lock");
        fs::write(&path, "leftover file").unwrap();
        let first = InstanceGuard::acquire_at(&path).unwrap().unwrap();
        assert!(InstanceGuard::acquire_at(&path).unwrap().is_none());
        drop(first);
        let next = InstanceGuard::acquire_at(&path).unwrap().unwrap();
        drop(next);
        assert_eq!(fs::read_to_string(path).unwrap(), "leftover file");
    }
    #[test]
    fn concurrent_starts_have_exactly_one_owner() {
        use std::sync::{
            atomic::{AtomicUsize, Ordering},
            Arc, Barrier,
        };
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("instance.lock");
        let start = Arc::new(Barrier::new(9));
        let attempted = Arc::new(Barrier::new(9));
        let owners = Arc::new(AtomicUsize::new(0));
        let mut threads = vec![];
        for _ in 0..8 {
            let (path, start, attempted, owners) = (
                path.clone(),
                start.clone(),
                attempted.clone(),
                owners.clone(),
            );
            threads.push(std::thread::spawn(move || {
                start.wait();
                let guard = InstanceGuard::acquire_at(&path).unwrap();
                if guard.is_some() {
                    owners.fetch_add(1, Ordering::SeqCst);
                }
                attempted.wait();
                drop(guard);
            }));
        }
        start.wait();
        attempted.wait();
        for thread in threads {
            thread.join().unwrap();
        }
        assert_eq!(owners.load(Ordering::SeqCst), 1);
        assert!(InstanceGuard::acquire_at(&path).unwrap().is_some());
    }
    #[test]
    fn filesystem_errors_are_not_reported_as_an_existing_instance() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("not-a-directory");
        fs::write(&path, "").unwrap();
        assert!(InstanceGuard::acquire_at(&path.join("instance.lock")).is_err());
    }
}
