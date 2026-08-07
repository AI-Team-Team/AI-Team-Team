# Gated Paginator Reading Flowchart

This document visualizes the control flow and slice boundaries enforced by the size-aware `GatedFileReader`.

## 1. Gated Read File Decision Flowchart

This flowchart outlines the logic executed when an agent node calls the `read_file(path, start_line, end_line)` tool:

```mermaid
flowchart TD
    Start["Call read_file(path, start_line, end_line)"] --> FileExist{"File exists on disk?"}
    
    FileExist -- "No" --> ReturnError["Return error: File does not exist"]
    FileExist -- "Yes" --> GetSize["Fetch file size in KB"]
    
    GetSize --> SizeGate{"Size exceeds large_file_threshold_kb?\n(default: 50 KB)"}
    
    SizeGate -- "Yes" --> EndLineGate{"Coordinates supplied?\n(end_line is not None)"}
    
    EndLineGate -- "No" --> CountLines["1. Scan file and count total lines\n2. Extract first 5 lines sample\n3. Prepend LARGE FILE WARNING"]
    CountLines --> ReturnOutline["Return Outline Warning payload"]
    
    EndLineGate -- "Yes" --> CalculateCap["Calculate requested window:\nWindow = end_line - start_line + 1"]
    SizeGate -- "No" --> DefaultEndLine{"end_line supplied?"}
    
    DefaultEndLine -- "No" --> CalculateCapDefault["Set end_line = start_line + max_chunk_lines - 1\nWindow = max_chunk_lines (100)"]
    DefaultEndLine -- "Yes" --> CalculateCap
    
    CalculateCap --> CapCheck{"Window exceeds max_chunk_lines?"}
    CalculateCapDefault --> CapCheck
    
    CapCheck -- "Yes" --> ShrinkWindow["Auto-shrink: Set end_line = start_line + max_chunk_lines - 1"]
    ShrinkWindow --> ReadSlice["Read lines from start_line to end_line\n(Prepend line numbers 'idx: content')"]
    
    CapCheck -- "No" --> ReadSlice
    
    ReadSlice --> ReturnChunk["Return line-numbered text slice"]
```

## 2. Streaming Tail Read Decision Flowchart

This flowchart visualizes the log tailing helper `read_file_tail(path, line_count)`:

```mermaid
flowchart TD
    StartTail["Call read_file_tail(path, line_count)"] --> FileCheck{"File exists?"}
    
    FileCheck -- "No" --> ReturnErr["Return error: File not found"]
    FileCheck -- "Yes" --> CountTotal["Scan and count total_lines in file"]
    
    CountTotal --> OffsetCalc["Calculate offset start:\nstart_line = max(1, total_lines - line_count + 1)"]
    OffsetCalc --> ReadTailSlice["Read lines from start_line to total_lines\n(Prepend line numbers 'idx: content')"]
    
    ReadTailSlice --> ReturnTail["Return line-numbered tail slice"]
```

## 3. DocLib ACL Segment-Based Path Permission Resolution Flowchart

This flowchart details the segment-based folder/file path traversal logic executed during `check_library_access` to evaluate read/write permissions:

```mermaid
flowchart TD
    Start["Call check_library_access(team_id, lib_id, path, required_permission)"] --> IsOwner{"Is team_id == lib.owner_team_id?"}
    
    IsOwner -- "Yes" --> ApproveOwner["Approve Access (Return True)"]
    IsOwner -- "No" --> HasPerms{"Any permissions defined for lib_id?"}
    
    HasPerms -- "No" --> DenyAccess["Deny Access (Return False)"]
    
    HasPerms -- "Yes" --> DecomposePath["Clean path & decompose into segments:<br/>e.g., '/specs/sub/file.txt' becomes:<br/>['/specs/sub/file.txt', '/specs/sub', '/specs', '/']"]
    
    DecomposePath --> LoopSegments["For each segment p in segments<br/>(ordered from deepest to root '/')"]
    
    LoopSegments --> HasSegmentPerm{"Has permission registered for segment p?"}
    
    HasSegmentPerm -- "No" --> NextSegment["Next segment in loop"]
    
    HasSegmentPerm -- "Yes" --> TeamInPerm{"Is team_id granted permission for p?"}
    
    TeamInPerm -- "No" --> NextSegment
    TeamInPerm -- "Yes" --> ResolvePerm{"Verify permission type:"}
    
    ResolvePerm -- "required_permission == 'READ'" --> CheckRead{"Granted permission is 'READ' or 'WRITE'?"}
    CheckRead -- "Yes" --> ApproveAccess["Approve Access (Return True)"]
    CheckRead -- "No" --> NextSegment
    
    ResolvePerm -- "required_permission == 'WRITE'" --> CheckWrite{"Granted permission is 'WRITE'?"}
    CheckWrite -- "Yes" --> ApproveAccess
    CheckWrite -- "No" --> NextSegment
    
    NextSegment --> LoopEnd{"More segments to evaluate?"}
    LoopEnd -- "Yes" --> LoopSegments
    LoopEnd -- "No" --> DenyAccess
```

Managed cross-library file links add a second resolution phase after source authorization. ATT follows `lib_id + relative path` metadata, repeats the same ACL check at every hop for the requested permission, rejects cycles, and opens only the final physical file. No operating-system symlink is followed.
