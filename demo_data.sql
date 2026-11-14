USE strava;

START TRANSACTION;

INSERT INTO users (username, email, password_hash)
VALUES
  ('demo_alex', 'alex.demo@example.test', SHA2('demo-only-alex', 256)),
  ('demo_jamie', 'jamie.demo@example.test', SHA2('demo-only-jamie', 256)),
  ('demo_taylor', 'taylor.demo@example.test', SHA2('demo-only-taylor', 256)),
  ('demo_morgan', 'morgan.demo@example.test', SHA2('demo-only-morgan', 256)),
  ('demo_riley', 'riley.demo@example.test', SHA2('demo-only-riley', 256))
ON DUPLICATE KEY UPDATE
  email = VALUES(email);

INSERT INTO routes (user_id, route_name, distance, elevation, description)
SELECT u.user_id, seed.route_name, seed.distance, seed.elevation, seed.description
FROM (
  SELECT 'demo_alex' AS username, 'Harbour Loop' AS route_name, 8.40 AS distance, 65.00 AS elevation, 'An easy loop along the waterfront.' AS description
  UNION ALL SELECT 'demo_jamie', 'Peak Trail', 12.60, 540.00, 'A hilly trail with a view from the top.'
  UNION ALL SELECT 'demo_taylor', 'Riverside Spin', 24.00, 110.00, 'A relaxed ride beside the river.'
  UNION ALL SELECT 'demo_morgan', 'Park Laps', 5.00, 18.00, 'A flat route through the city park.'
  UNION ALL SELECT 'demo_riley', 'Coastal Ride', 36.50, 230.00, 'A longer ride along the coast.'
) AS seed
JOIN users u ON u.username = seed.username
WHERE NOT EXISTS (
  SELECT 1
  FROM routes existing
  WHERE existing.user_id = u.user_id
    AND existing.route_name = seed.route_name
);

INSERT INTO activities (
  user_id, route_id, title, description, distance, activity_date, duration
)
SELECT
  u.user_id,
  r.route_id,
  seed.title,
  seed.description,
  seed.distance,
  DATE_SUB(CURRENT_DATE, INTERVAL seed.days_ago DAY) + INTERVAL 7 HOUR,
  seed.duration
FROM (
  SELECT 'demo_alex' AS username, 'Harbour Loop' AS route_name, 'Morning easy run' AS title, 'A steady start to the week.' AS description, 8.40 AS distance, 1 AS days_ago, 2700 AS duration
  UNION ALL SELECT 'demo_jamie', 'Peak Trail', 'Summit trail run', 'Took the scenic route today.', 12.60, 2, 5100
  UNION ALL SELECT 'demo_taylor', 'Riverside Spin', 'Evening ride', 'An easy spin after work.', 24.00, 3, 3900
  UNION ALL SELECT 'demo_morgan', 'Park Laps', 'Lunch break run', 'A few quiet laps in the park.', 5.00, 4, 1680
  UNION ALL SELECT 'demo_riley', 'Coastal Ride', 'Coastal miles', 'Sunny skies and a long ride.', 36.50, 5, 6000
  UNION ALL SELECT 'demo_alex', 'Harbour Loop', 'Weekend long run', 'Kept the pace comfortable.', 10.20, 7, 3300
  UNION ALL SELECT 'demo_jamie', 'Peak Trail', 'Hill repeats', 'Short efforts on the climb.', 7.80, 8, 3600
  UNION ALL SELECT 'demo_taylor', 'Riverside Spin', 'River path ride', 'Cruised along the water.', 31.20, 9, 5100
  UNION ALL SELECT 'demo_morgan', 'Park Laps', 'Easy recovery run', 'Gentle pace, fresh legs.', 4.20, 11, 1500
  UNION ALL SELECT 'demo_riley', 'Coastal Ride', 'Sunday endurance ride', 'A relaxed ride with a coffee stop.', 42.00, 13, 7200
  UNION ALL SELECT 'demo_alex', 'Harbour Loop', 'Quick morning run', 'A short route before breakfast.', 6.10, 15, 1980
) AS seed
JOIN users u ON u.username = seed.username
JOIN routes r ON r.user_id = u.user_id AND r.route_name = seed.route_name
WHERE NOT EXISTS (
  SELECT 1
  FROM activities existing
  WHERE existing.user_id = u.user_id
    AND existing.title = seed.title
    AND existing.activity_date = DATE_SUB(CURRENT_DATE, INTERVAL seed.days_ago DAY) + INTERVAL 7 HOUR
);

INSERT INTO kudos (user_id, activity_id)
SELECT giver.user_id, a.activity_id
FROM (
  SELECT 'demo_jamie' AS giver_name, 'demo_alex' AS owner_name, 'Morning easy run' AS activity_title
  UNION ALL SELECT 'demo_taylor', 'demo_alex', 'Morning easy run'
  UNION ALL SELECT 'demo_alex', 'demo_jamie', 'Summit trail run'
  UNION ALL SELECT 'demo_morgan', 'demo_jamie', 'Summit trail run'
  UNION ALL SELECT 'demo_riley', 'demo_taylor', 'Evening ride'
  UNION ALL SELECT 'demo_alex', 'demo_taylor', 'Evening ride'
  UNION ALL SELECT 'demo_jamie', 'demo_morgan', 'Lunch break run'
  UNION ALL SELECT 'demo_taylor', 'demo_riley', 'Coastal miles'
) AS seed
JOIN users giver ON giver.username = seed.giver_name
JOIN users owner ON owner.username = seed.owner_name
JOIN activities a ON a.user_id = owner.user_id AND a.title = seed.activity_title
WHERE NOT EXISTS (
  SELECT 1
  FROM kudos existing
  WHERE existing.user_id = giver.user_id
    AND existing.activity_id = a.activity_id
);

INSERT INTO comments (user_id, activity_id, body)
SELECT commenter.user_id, a.activity_id, seed.body
FROM (
  SELECT 'demo_jamie' AS commenter_name, 'demo_alex' AS owner_name, 'Morning easy run' AS activity_title, 'Nice work getting out early!' AS body
  UNION ALL SELECT 'demo_taylor', 'demo_alex', 'Morning easy run', 'That route looks lovely.'
  UNION ALL SELECT 'demo_alex', 'demo_jamie', 'Summit trail run', 'Great climb - the view must have been worth it.'
  UNION ALL SELECT 'demo_riley', 'demo_taylor', 'Evening ride', 'A perfect way to end the day.'
  UNION ALL SELECT 'demo_morgan', 'demo_riley', 'Coastal miles', 'Adding this route to my list!'
) AS seed
JOIN users commenter ON commenter.username = seed.commenter_name
JOIN users owner ON owner.username = seed.owner_name
JOIN activities a ON a.user_id = owner.user_id AND a.title = seed.activity_title
WHERE NOT EXISTS (
  SELECT 1
  FROM comments existing
  WHERE existing.user_id = commenter.user_id
    AND existing.activity_id = a.activity_id
    AND existing.body = seed.body
);

INSERT INTO user_follows (follower_id, followed_id)
SELECT follower.user_id, followed.user_id
FROM (
  SELECT 'demo_alex' AS follower_name, 'demo_jamie' AS followed_name
  UNION ALL SELECT 'demo_alex', 'demo_taylor'
  UNION ALL SELECT 'demo_jamie', 'demo_alex'
  UNION ALL SELECT 'demo_jamie', 'demo_riley'
  UNION ALL SELECT 'demo_taylor', 'demo_alex'
  UNION ALL SELECT 'demo_taylor', 'demo_morgan'
  UNION ALL SELECT 'demo_morgan', 'demo_jamie'
  UNION ALL SELECT 'demo_riley', 'demo_taylor'
) AS seed
JOIN users follower ON follower.username = seed.follower_name
JOIN users followed ON followed.username = seed.followed_name
WHERE NOT EXISTS (
  SELECT 1
  FROM user_follows existing
  WHERE existing.follower_id = follower.user_id
    AND existing.followed_id = followed.user_id
);

COMMIT;
