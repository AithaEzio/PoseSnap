//! Seek over verified release parts without making a second multi-gigabyte archive.
use std::{fs::File, io::{self, Read, Seek, SeekFrom}, path::PathBuf};

pub struct JoinedFiles { files: Vec<File>, ends: Vec<u64>, position: u64 }
impl JoinedFiles {
    pub fn open(paths: &[PathBuf]) -> io::Result<Self> {
        let mut files = Vec::new(); let mut ends = Vec::new(); let mut total = 0u64;
        for path in paths {
            let file = File::open(path)?;
            total = total.checked_add(file.metadata()?.len()).ok_or_else(|| io::Error::other("Archive size overflow"))?;
            files.push(file); ends.push(total);
        }
        Ok(Self { files, ends, position: 0 })
    }
}
impl Read for JoinedFiles {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        let index = self.ends.partition_point(|end| *end <= self.position);
        if buffer.is_empty() || index == self.files.len() { return Ok(0); }
        let start = if index == 0 { 0 } else { self.ends[index-1] };
        let count = buffer.len().min((self.ends[index]-self.position) as usize);
        self.files[index].seek(SeekFrom::Start(self.position-start))?;
        let count = self.files[index].read(&mut buffer[..count])?;
        self.position += count as u64; Ok(count)
    }
}
impl Seek for JoinedFiles {
    fn seek(&mut self, from: SeekFrom) -> io::Result<u64> {
        let position = match from {
            SeekFrom::Start(value) => value as i128,
            SeekFrom::Current(value) => self.position as i128 + value as i128,
            SeekFrom::End(value) => self.ends.last().copied().unwrap_or(0) as i128 + value as i128,
        };
        self.position = u64::try_from(position).map_err(|_| io::Error::new(io::ErrorKind::InvalidInput,"Invalid archive seek"))?;
        Ok(self.position)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn reads_seams_end_and_backwards_without_combining_files() {
        let root=tempfile::tempdir().unwrap(); let mut paths=Vec::new();
        for (index,bytes) in [b"abc".as_slice(),b"",b"defg"].iter().enumerate() {
            let path=root.path().join(index.to_string());std::fs::write(&path,bytes).unwrap();paths.push(path);
        }
        let mut reader=JoinedFiles::open(&paths).unwrap();let mut data=String::new();reader.read_to_string(&mut data).unwrap();assert_eq!(data,"abcdefg");
        reader.seek(SeekFrom::End(-4)).unwrap();let mut data=[0;4];reader.read_exact(&mut data).unwrap();assert_eq!(&data,b"defg");
        reader.seek(SeekFrom::Start(1)).unwrap();reader.read_exact(&mut data).unwrap();assert_eq!(&data,b"bcde");
        assert!(reader.seek(SeekFrom::Current(-100)).is_err());
        reader.seek(SeekFrom::Start(100)).unwrap();assert_eq!(reader.read(&mut data).unwrap(),0);
    }
    #[test] fn zip_central_directory_and_payload_can_cross_any_part_boundary() {
        use std::io::{Cursor,Write};
        let mut zip=zip::ZipWriter::new(Cursor::new(Vec::new()));zip.start_file("models/test/data",zip::write::SimpleFileOptions::default()).unwrap();zip.write_all(b"verified payload").unwrap();
        let bytes=zip.finish().unwrap().into_inner();let root=tempfile::tempdir().unwrap();let mut paths=Vec::new();
        for (index,chunk) in bytes.chunks(11).enumerate(){let path=root.path().join(index.to_string());std::fs::write(&path,chunk).unwrap();paths.push(path);}
        let mut zip=zip::ZipArchive::new(JoinedFiles::open(&paths).unwrap()).unwrap();let mut value=String::new();zip.by_name("models/test/data").unwrap().read_to_string(&mut value).unwrap();assert_eq!(value,"verified payload");
    }
}
