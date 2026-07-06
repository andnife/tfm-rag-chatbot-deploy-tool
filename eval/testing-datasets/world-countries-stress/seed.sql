-- World Countries RAG Eval Dataset
-- Snapshot ~2023. DDL + INSERTs only. MySQL dialect.
-- Population in persons, area in km2, GDP in billions USD (nominal ~2023).
-- Continent values: 'Europa','Asia','América','África','Oceanía'
-- Currency and official_language in Spanish.

CREATE TABLE countries (
  id INT PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  capital VARCHAR(80) NOT NULL,
  population BIGINT NOT NULL,
  area_km2 INT NOT NULL,
  gdp_usd_bn DECIMAL(10,1) NOT NULL,
  continent VARCHAR(30) NOT NULL,
  currency VARCHAR(40) NOT NULL,
  official_language VARCHAR(60) NOT NULL
);

CREATE TABLE cities (
  id INT PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  country VARCHAR(80) NOT NULL,
  population INT NOT NULL,
  is_capital TINYINT NOT NULL
);

-- ============================================================
-- COUNTRIES (40 rows)
-- ============================================================
INSERT INTO countries VALUES
-- 10 documented countries
(1,  'España',       'Madrid',        47400000,   505990,  1580.7, 'Europa',   'Euro',              'Español'),
(2,  'Francia',      'París',         68000000,   643801,  2923.5, 'Europa',   'Euro',              'Francés'),
(3,  'Japón',        'Tokio',        125700000,   377930,  4409.7, 'Asia',     'Yen',               'Japonés'),
(4,  'Brasil',       'Brasilia',     215300000,  8515767,  2081.2, 'América',  'Real brasileño',    'Portugués'),
(5,  'Egipto',       'El Cairo',     105000000,  1001449,   396.3, 'África',   'Libra egipcia',     'Árabe'),
(6,  'Australia',    'Canberra',      26500000,  7692024,  1707.5, 'Oceanía',  'Dólar australiano', 'Inglés'),
(7,  'Canadá',       'Ottawa',        38900000,  9984670,  2139.8, 'América',  'Dólar canadiense',  'Inglés'),
(8,  'India',        'Nueva Delhi', 1428600000,  3287263,  3732.2, 'Asia',     'Rupia india',       'Hindi'),
(9,  'Alemania',     'Berlín',        84300000,   357114,  4430.0, 'Europa',   'Euro',              'Alemán'),
(10, 'Sudáfrica',    'Pretoria',      60400000,  1219090,   405.2, 'África',   'Rand sudafricano',  'Zulú'),
-- 30 additional countries
(11, 'China',        'Pekín',       1409670000,  9596960, 17701.9, 'Asia',     'Yuan',              'Chino mandarín'),
(12, 'Estados Unidos','Washington D.C.',335000000,9833517,27360.9,'América',  'Dólar estadounidense','Inglés'),
(13, 'Reino Unido',  'Londres',       67700000,   242495,  3332.0, 'Europa',   'Libra esterlina',   'Inglés'),
(14, 'Italia',       'Roma',          58900000,   301338,  2254.4, 'Europa',   'Euro',              'Italiano'),
(15, 'México',       'Ciudad de México',128500000,1964375, 1322.5, 'América',  'Peso mexicano',     'Español'),
(16, 'Argentina',    'Buenos Aires',  45800000,  2780400,   632.8, 'América',  'Peso argentino',    'Español'),
(17, 'Rusia',        'Moscú',        144400000, 17098242,  1862.5, 'Europa',   'Rublo ruso',        'Ruso'),
(18, 'Turquía',      'Ankara',        85300000,   783562,  1154.6, 'Asia',     'Lira turca',        'Turco'),
(19, 'Corea del Sur','Seúl',          51700000,   100210,  1709.2, 'Asia',     'Won surcoreano',    'Coreano'),
(20, 'Indonesia',    'Yakarta',      277500000,  1904569,  1319.1, 'Asia',     'Rupia indonesia',   'Indonesio'),
(21, 'Arabia Saudí', 'Riad',          36400000,  2149690,  1062.2, 'Asia',     'Riyal saudí',       'Árabe'),
(22, 'Nigeria',      'Abuya',        223800000,   923768,   477.4, 'África',   'Naira nigeriana',   'Inglés'),
(23, 'Etiopía',      'Addis Abeba',  126500000,  1104300,   155.8, 'África',   'Birr etíope',       'Amhárico'),
(24, 'Kenia',        'Nairobi',       55100000,   582646,   118.1, 'África',   'Chelín keniano',    'Suajili'),
(25, 'Marruecos',    'Rabat',         37700000,   446550,   141.1, 'África',   'Dírham marroquí',   'Árabe'),
(26, 'Colombia',     'Bogotá',        51870000,  1141748,   363.8, 'América',  'Peso colombiano',   'Español'),
(27, 'Chile',        'Santiago',      19600000,   756102,   344.5, 'América',  'Peso chileno',      'Español'),
(28, 'Perú',         'Lima',          33400000,  1285216,   268.6, 'América',  'Sol peruano',       'Español'),
(29, 'Venezuela',    'Caracas',       28800000,   916445,   102.3, 'América',  'Bolívar venezolano','Español'),
(30, 'Portugal',     'Lisboa',        10400000,    92212,   272.0, 'Europa',   'Euro',              'Portugués'),
(31, 'Polonia',      'Varsovia',      38000000,   312696,   842.2, 'Europa',   'Esloti polaco',     'Polaco'),
(32, 'Suecia',       'Estocolmo',     10500000,   450295,   597.1, 'Europa',   'Corona sueca',      'Sueco'),
(33, 'Noruega',      'Oslo',           5500000,   385207,   546.8, 'Europa',   'Corona noruega',    'Noruego'),
(34, 'Países Bajos', 'Ámsterdam',     17900000,    41543,  1118.1, 'Europa',   'Euro',              'Neerlandés'),
(35, 'Bélgica',      'Bruselas',      11600000,    30528,   627.5, 'Europa',   'Euro',              'Neerlandés'),
(36, 'Suiza',        'Berna',          8800000,    41285,   905.7, 'Europa',   'Franco suizo',      'Alemán'),
(37, 'Nueva Zelanda','Wellington',     5100000,   270467,   247.2, 'Oceanía',  'Dólar neozelandés', 'Inglés'),
(38, 'Pakistán',     'Islamabad',    231400000,   881913,   338.4, 'Asia',     'Rupia pakistaní',   'Urdu'),
(39, 'Bangladesh',   'Daca',          170000000,  147570,   460.2, 'Asia',     'Taka bangladesí',   'Bengalí'),
(40, 'Vietnam',      'Hanói',         98900000,   331212,   433.6, 'Asia',     'Dong vietnamita',   'Vietnamita');

-- ============================================================
-- CITIES (61 rows)
-- 40 capitals (is_capital=1) + 21 large non-capital cities (is_capital=0)
-- ============================================================
INSERT INTO cities VALUES
-- Capitals
(1,  'Madrid',           'España',           3300000,  1),
(2,  'París',            'Francia',          2161000,  1),
(3,  'Tokio',            'Japón',           13960000,  1),
(4,  'Brasilia',         'Brasil',            3055000,  1),
(5,  'El Cairo',         'Egipto',           20900000,  1),
(6,  'Canberra',         'Australia',          462000,  1),
(7,  'Ottawa',           'Canadá',            1017000,  1),
(8,  'Nueva Delhi',      'India',             32900000, 1),
(9,  'Berlín',           'Alemania',          3769000,  1),
(10, 'Pretoria',         'Sudáfrica',          741000,  1),
(11, 'Pekín',            'China',            21900000,  1),
(12, 'Washington D.C.', 'Estados Unidos',     689000,  1),
(13, 'Londres',          'Reino Unido',       9541000,  1),
(14, 'Roma',             'Italia',            2873000,  1),
(15, 'Ciudad de México', 'México',           21600000,  1),
(16, 'Buenos Aires',     'Argentina',        15490000,  1),
(17, 'Moscú',            'Rusia',            12500000,  1),
(18, 'Ankara',           'Turquía',           5746000,  1),
(19, 'Seúl',             'Corea del Sur',     9776000,  1),
(20, 'Yakarta',          'Indonesia',        34500000,  1),
(21, 'Riad',             'Arabia Saudí',      7676000,  1),
(22, 'Abuya',            'Nigeria',           3464000,  1),
(23, 'Addis Abeba',      'Etiopía',           5006000,  1),
(24, 'Nairobi',          'Kenia',             4922000,  1),
(25, 'Rabat',            'Marruecos',         1800000,  1),
(26, 'Bogotá',           'Colombia',         11344000,  1),
(27, 'Santiago',         'Chile',             7400000,  1),
(28, 'Lima',             'Perú',             11200000,  1),
(29, 'Caracas',          'Venezuela',         3200000,  1),
(30, 'Lisboa',           'Portugal',          2942000,  1),
(31, 'Varsovia',         'Polonia',           1860000,  1),
(32, 'Estocolmo',        'Suecia',            1000000,  1),
(33, 'Oslo',             'Noruega',            717000,  1),
(34, 'Ámsterdam',        'Países Bajos',      1157000,  1),
(35, 'Bruselas',         'Bélgica',           1212000,  1),
(36, 'Berna',            'Suiza',              134000,  1),
(37, 'Wellington',       'Nueva Zelanda',      215000,  1),
(38, 'Islamabad',        'Pakistán',          2151000,  1),
(39, 'Daca',             'Bangladesh',       22480000,  1),
(40, 'Hanói',            'Vietnam',           8330000,  1),
-- Non-capital cities
(41, 'Barcelona',        'España',            5600000,  0),
(42, 'Marsella',         'Francia',           1760000,  0),
(43, 'Osaka',            'Japón',             8800000,  0),
(44, 'São Paulo',        'Brasil',           22430000,  0),
(45, 'Alejandría',       'Egipto',            5200000,  0),
(46, 'Sídney',           'Australia',         5312000,  0),
(47, 'Toronto',          'Canadá',            6255000,  0),
(48, 'Bombay',           'India',            20700000,  0),
(49, 'Hamburgo',         'Alemania',          1900000,  0),
(50, 'Ciudad del Cabo',  'Sudáfrica',         4618000,  0),
(51, 'Shanghái',         'China',            26320000,  0),
(52, 'Nueva York',       'Estados Unidos',   18804000,  0),
(53, 'Mánchester',       'Reino Unido',       2730000,  0),
(54, 'Milán',            'Italia',            3140000,  0),
(55, 'Guadalajara',      'México',            5209000,  0),
(56, 'Estambul',         'Turquía',          15460000,  0),
(57, 'Busán',            'Corea del Sur',     3440000,  0),
(58, 'Surabaya',         'Indonesia',         2765000,  0),
(59, 'Lagos',            'Nigeria',          15388000,  0),
(60, 'Ho Chi Minh',      'Vietnam',           9320000,  0),
(61, 'Karachi',          'Pakistán',         14910000,  0);
