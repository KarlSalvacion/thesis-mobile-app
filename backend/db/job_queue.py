def create_processing_job_impl(get_db_connection, job_id, original_filename, is_video=False, is_image=False, has_srt=False):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO processing_jobs
            (job_id, status, progress, original_filename, is_video, is_image, has_srt)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''',
            (job_id, 'queued', 'Uploaded, starting processing...', original_filename, is_video, is_image, has_srt),
        )
        conn.commit()


def update_job_status_impl(get_db_connection, job_id, status, progress=None, error_message=None):
    with get_db_connection() as conn:
        cursor = conn.cursor()

        updates = ['status = %s', 'updated_at = CURRENT_TIMESTAMP']
        values = [status]

        if progress is not None:
            updates.append('progress = %s')
            values.append(progress)

        if error_message is not None:
            updates.append('error_message = %s')
            values.append(error_message)

        if status in ['completed', 'failed']:
            updates.append('completed_at = CURRENT_TIMESTAMP')

        values.append(job_id)

        query = f"UPDATE processing_jobs SET {', '.join(updates)} WHERE job_id = %s"
        cursor.execute(query, values)
        conn.commit()


def update_job_result_impl(get_db_connection, update_detection, job_id, detection_id, result_json, annotated_url=None, temp_video_path=None, needs_compression=False):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE processing_jobs
            SET detection_id = %s,
                status = %s,
                progress = %s,
                result_json = %s,
                temp_video_path = %s,
                needs_client_compression = %s,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE job_id = %s
        ''',
            (detection_id, 'completed', 'Processing complete', result_json, temp_video_path, needs_compression, job_id),
        )

        if annotated_url:
            update_detection(detection_id, cloud_annotated_url=annotated_url)

        conn.commit()


def get_job_status_impl(get_db_connection, real_dict_cursor, job_id):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=real_dict_cursor)
        cursor.execute('SELECT * FROM processing_jobs WHERE job_id = %s', (job_id,))
        result = cursor.fetchone()
        return dict(result) if result else None


def mark_compression_completed_impl(get_db_connection, job_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE processing_jobs
            SET status = %s,
                progress = %s,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CURRENT_TIMESTAMP
            WHERE job_id = %s
        ''',
            ('completed', 'Compression complete', job_id),
        )
        conn.commit()


def get_pending_compression_jobs_impl(get_db_connection, real_dict_cursor):
    with get_db_connection() as conn:
        cursor = conn.cursor(cursor_factory=real_dict_cursor)
        cursor.execute(
            '''
            SELECT * FROM processing_jobs
            WHERE status IN ('pending', 'processing', 'queued')
            ORDER BY created_at ASC
        '''
        )
        return [dict(row) for row in cursor.fetchall()]


def cleanup_old_jobs_impl(get_db_connection, days=7):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''
            DELETE FROM processing_jobs
            WHERE status IN ('completed', 'failed')
            AND created_at < (CURRENT_TIMESTAMP - INTERVAL '%s days')
        ''',
            (days,),
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted
